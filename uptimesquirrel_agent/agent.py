#!/usr/bin/env python3
"""
UptimeSquirrel System Monitoring Agent v1.2.0
Collects system metrics and reports to UptimeSquirrel API

New in v1.2.0:
- Remote threshold configuration from server
- Improved error handling and retry logic
- Better connection management
- Local metric buffering for offline scenarios

New in v1.1.0:
- Disk I/O metrics with read/write rates and IOPS
- Temperature/thermal data collection (CPU/GPU)
- Process and thread counting
- Network delta calculations for accurate bandwidth monitoring
"""

import os
import sys
import time
import json
import socket
import platform
import configparser
import logging
import argparse
from datetime import datetime
from typing import Dict, Optional, List
import psutil
import requests
from requests.adapters import HTTPAdapter
from http.client import RemoteDisconnected
from urllib3.util.retry import Retry
from collections import deque
import threading

# Optional SNMP support
try:
    from snmp_collector import SNMPCollector, SNMPDevice, SNMPVersion, load_snmp_config
    SNMP_AVAILABLE = True
except ImportError:
    SNMP_AVAILABLE = False
    logging.info("SNMP support not available. Install pysnmp to enable SNMP monitoring.")

# Version
__version__ = "1.2.7"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('uptimesquirrel-agent')


class MetricCollector:
    """Base class for metric collectors"""
    
    def collect(self) -> Dict:
        raise NotImplementedError


class CPUCollector(MetricCollector):
    """Collects CPU metrics"""
    
    def collect(self) -> Dict:
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()
        load_avg = os.getloadavg()
        
        return {
            'usage_percent': cpu_percent,
            'count': cpu_count,
            'load_average': {
                '1min': load_avg[0],
                '5min': load_avg[1],
                '15min': load_avg[2]
            }
        }


class MemoryCollector(MetricCollector):
    """Collects memory metrics"""
    
    def collect(self) -> Dict:
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        
        return {
            'total': mem.total,
            'available': mem.available,
            'used': mem.used,
            'free': mem.free,
            'percent': mem.percent,
            'swap': {
                'total': swap.total,
                'used': swap.used,
                'free': swap.free,
                'percent': swap.percent
            }
        }


class DiskCollector(MetricCollector):
    """Collects disk usage metrics"""
    
    def __init__(self, config_dir: str = None):
        self.config_dir = config_dir or "/etc/uptimesquirrel"
        self.disk_config = self.load_disk_config()
        self.last_config_check = time.time()
        self.config_check_interval = 60  # Check for config changes every minute
    
    def load_disk_config(self) -> Dict:
        """Load disk monitoring configuration"""
        config_file = os.path.join(self.config_dir, "disks.json")
        
        # Check if config file exists
        if not os.path.exists(config_file):
            # Create default config with all discovered disks
            self.create_default_disk_config(config_file)
        
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
                logger.info(f"Loaded disk configuration from {config_file}")
                return config
        except Exception as e:
            logger.error(f"Failed to load disk config: {e}")
            return {"disks": {}, "enabled": True}
    
    def create_default_disk_config(self, config_file: str):
        """Create default disk configuration with all discovered disks"""
        logger.info("Creating default disk configuration...")
        
        # Discover all disks
        discovered_disks = {}
        for partition in psutil.disk_partitions():
            if partition.fstype:
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    # Skip tiny partitions (< 1GB)
                    if usage.total < 1024 * 1024 * 1024:
                        continue
                    
                    discovered_disks[partition.mountpoint] = {
                        "enabled": True,
                        "device": partition.device,
                        "fstype": partition.fstype,
                        "description": f"{partition.device} ({self._format_bytes(usage.total)})"
                    }
                except:
                    pass
        
        config = {
            "comment": "Disk monitoring configuration for UptimeSquirrel agent",
            "note": "Only 4 disks will show in charts, but all enabled disks will be monitored for alerts",
            "instructions": "Set 'enabled' to false for any disk you don't want to monitor",
            "enabled": True,
            "disks": discovered_disks
        }
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(config_file), exist_ok=True)
        
        try:
            with open(config_file, 'w') as f:
                json.dump(config, f, indent=2)
            logger.info(f"Created disk configuration at {config_file}")
        except Exception as e:
            logger.error(f"Failed to create disk config: {e}")
    
    def _format_bytes(self, bytes_val: int) -> str:
        """Format bytes to human-readable string"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_val < 1024.0:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024.0
        return f"{bytes_val:.1f} PB"
    
    def collect(self) -> Dict:
        # Reload config periodically
        if time.time() - self.last_config_check > self.config_check_interval:
            self.disk_config = self.load_disk_config()
            self.last_config_check = time.time()
        
        # Check if disk monitoring is enabled globally
        if not self.disk_config.get("enabled", True):
            return {}
        
        disks = {}
        disk_configs = self.disk_config.get("disks", {})
        
        for partition in psutil.disk_partitions():
            if partition.fstype:
                # Check if this disk is in our config and enabled
                disk_config = disk_configs.get(partition.mountpoint, {})
                if not disk_config.get("enabled", True):
                    continue
                
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    disks[partition.mountpoint] = {
                        'device': partition.device,
                        'fstype': partition.fstype,
                        'total': usage.total,
                        'used': usage.used,
                        'free': usage.free,
                        'percent': usage.percent,
                        'description': disk_config.get('description', f"{partition.device} ({self._format_bytes(usage.total)})")
                    }
                except PermissionError:
                    # This can happen on Windows
                    pass
        
        return disks


class DiskIOCollector(MetricCollector):
    """Collects disk I/O metrics"""
    
    def __init__(self):
        self.last_counters = None
        self.last_time = None
    
    def collect(self) -> Dict:
        """Collect disk I/O metrics with rate calculations"""
        current_time = time.time()
        counters = psutil.disk_io_counters(perdisk=True)
        
        if not counters:
            return {}
        
        io_data = {}
        
        # If we have previous data, calculate rates
        if self.last_counters and self.last_time:
            time_delta = current_time - self.last_time
            
            for disk, current in counters.items():
                if disk in self.last_counters:
                    previous = self.last_counters[disk]
                    
                    # Calculate bytes per second
                    read_rate = (current.read_bytes - previous.read_bytes) / time_delta
                    write_rate = (current.write_bytes - previous.write_bytes) / time_delta
                    
                    # Calculate IOPS
                    read_iops = (current.read_count - previous.read_count) / time_delta
                    write_iops = (current.write_count - previous.write_count) / time_delta
                    
                    io_data[disk] = {
                        'read_bytes_per_sec': int(read_rate),
                        'write_bytes_per_sec': int(write_rate),
                        'read_iops': round(read_iops, 2),
                        'write_iops': round(write_iops, 2),
                        'read_count': current.read_count,
                        'write_count': current.write_count,
                        'read_bytes': current.read_bytes,
                        'write_bytes': current.write_bytes
                    }
        else:
            # First run, just store absolute values
            for disk, current in counters.items():
                io_data[disk] = {
                    'read_bytes_per_sec': 0,
                    'write_bytes_per_sec': 0,
                    'read_iops': 0,
                    'write_iops': 0,
                    'read_count': current.read_count,
                    'write_count': current.write_count,
                    'read_bytes': current.read_bytes,
                    'write_bytes': current.write_bytes
                }
        
        # Store current values for next calculation
        self.last_counters = counters
        self.last_time = current_time
        
        return io_data


class NetworkCollector(MetricCollector):
    """Collects network metrics with delta calculations"""
    
    def __init__(self):
        self.last_counters = None
        self.last_time = None
    
    def collect(self) -> Dict:
        """Collect network metrics with bandwidth calculations"""
        current_time = time.time()
        counters = psutil.net_io_counters(pernic=True)
        
        # Debug: log available network interfaces
        logger.debug(f"Available network interfaces: {list(counters.keys())}")
        
        network_data = {}
        
        # If we have previous data, calculate rates
        if self.last_counters and self.last_time:
            time_delta = current_time - self.last_time
            
            for interface, current in counters.items():
                # Skip loopback interface
                if interface.startswith('lo'):
                    logger.debug(f"Skipping loopback interface: {interface}")
                    continue
                    
                if interface in self.last_counters:
                    previous = self.last_counters[interface]
                    
                    # Calculate bytes per second (bandwidth)
                    bytes_sent_per_sec = (current.bytes_sent - previous.bytes_sent) / time_delta
                    bytes_recv_per_sec = (current.bytes_recv - previous.bytes_recv) / time_delta
                    
                    # Calculate packets per second
                    packets_sent_per_sec = (current.packets_sent - previous.packets_sent) / time_delta
                    packets_recv_per_sec = (current.packets_recv - previous.packets_recv) / time_delta
                    
                    network_data[interface] = {
                        'bytes_sent': current.bytes_sent,
                        'bytes_recv': current.bytes_recv,
                        'packets_sent': current.packets_sent,
                        'packets_recv': current.packets_recv,
                        'bytes_sent_per_sec': int(bytes_sent_per_sec),
                        'bytes_recv_per_sec': int(bytes_recv_per_sec),
                        'packets_sent_per_sec': round(packets_sent_per_sec, 2),
                        'packets_recv_per_sec': round(packets_recv_per_sec, 2),
                        'errin': current.errin,
                        'errout': current.errout,
                        'dropin': current.dropin,
                        'dropout': current.dropout
                    }
        else:
            # First run, just store absolute values
            for interface, current in counters.items():
                # Skip loopback interface
                if interface.startswith('lo'):
                    logger.debug(f"Skipping loopback interface: {interface}")
                    continue
                    
                network_data[interface] = {
                    'bytes_sent': current.bytes_sent,
                    'bytes_recv': current.bytes_recv,
                    'packets_sent': current.packets_sent,
                    'packets_recv': current.packets_recv,
                    'bytes_sent_per_sec': 0,
                    'bytes_recv_per_sec': 0,
                    'packets_sent_per_sec': 0,
                    'packets_recv_per_sec': 0,
                    'errin': current.errin,
                    'errout': current.errout,
                    'dropin': current.dropin,
                    'dropout': current.dropout
                }
        
        # Store current values for next calculation
        self.last_counters = counters
        self.last_time = current_time
        
        # Debug logging
        if network_data:
            logger.debug(f"NetworkCollector returning data: {network_data}")
        else:
            logger.warning("NetworkCollector returning empty data")
        
        return network_data


class ServiceCollector(MetricCollector):
    """Collects service status for both systemd services and Docker containers"""
    
    def __init__(self, services: List[str]):
        self.services = services
        # Check if Docker is available
        self.docker_available = self._check_docker_available()
        if self.docker_available:
            logger.info("Docker support enabled for service monitoring")
        else:
            logger.info("Docker not available, using systemd only")
    
    def _check_docker_available(self) -> bool:
        """Check if Docker is installed and accessible"""
        try:
            import subprocess
            result = subprocess.run(
                ['docker', '--version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except:
            return False
    
    def collect(self) -> Dict:
        service_status = {}
        
        for service in self.services:
            try:
                if service.startswith('docker-') and self.docker_available:
                    # Handle Docker container
                    container_name = service[7:]  # Remove 'docker-' prefix
                    service_status[service] = self._check_docker_container(container_name)
                else:
                    # Handle regular systemd service
                    service_status[service] = self._check_systemd_service(service)
                    
            except Exception as e:
                logger.debug(f"Error checking service {service}: {e}")
                service_status[service] = {
                    'active': False,
                    'status': 'error',
                    'error': str(e)
                }
        
        return service_status
    
    def _check_docker_container(self, container_name: str) -> Dict:
        """Check Docker container status with health information"""
        import subprocess
        
        try:
            # Get container state
            state_result = subprocess.run(
                ['docker', 'inspect', container_name, 
                 '--format={{.State.Status}}|{{.State.Running}}|{{.State.Health.Status}}|{{.RestartCount}}'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if state_result.returncode != 0:
                # Container doesn't exist
                return {
                    'active': False,
                    'status': 'not_found',
                    'type': 'docker',
                    'error': f"Container {container_name} not found"
                }
            
            # Parse the output
            parts = state_result.stdout.strip().split('|')
            container_status = parts[0] if len(parts) > 0 else 'unknown'
            is_running = parts[1] == 'true' if len(parts) > 1 else False
            health_status = parts[2] if len(parts) > 2 and parts[2] else None
            restart_count = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
            
            # Determine if container is "active"
            # Container is active if it's running and either healthy or has no health check
            if is_running:
                if health_status:
                    active = health_status == 'healthy'
                    status = f"{container_status} ({health_status})"
                else:
                    active = True
                    status = container_status
            else:
                active = False
                status = container_status
            
            return {
                'active': active,
                'status': status,
                'type': 'docker',
                'container_name': container_name,
                'restart_count': restart_count,
                'health_status': health_status
            }
            
        except subprocess.TimeoutExpired:
            return {
                'active': False,
                'status': 'timeout',
                'type': 'docker',
                'error': 'Docker command timed out'
            }
        except Exception as e:
            return {
                'active': False,
                'status': 'error',
                'type': 'docker',
                'error': str(e)
            }
    
    def _check_systemd_service(self, service: str) -> Dict:
        """Check systemd service status"""
        import subprocess
        
        try:
            result = subprocess.run(
                ['systemctl', 'is-active', service],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            active = result.returncode == 0
            status = result.stdout.strip()
            
            return {
                'active': active,
                'status': status,
                'type': 'systemd'
            }
        except Exception as e:
            return {
                'active': False,
                'status': 'error',
                'type': 'systemd',
                'error': str(e)
            }


class ThermalCollector(MetricCollector):
    """Collects temperature/thermal data"""
    
    def collect(self) -> Dict:
        thermal_data = {}
        
        try:
            # Try to get temperature sensors
            temperatures = psutil.sensors_temperatures()
            
            # Look for CPU temperature
            cpu_temp = None
            gpu_temp = None
            
            # Common CPU temperature sensor names
            cpu_sensors = ['coretemp', 'cpu_thermal', 'k10temp', 'acpi']
            for sensor_name in cpu_sensors:
                if sensor_name in temperatures:
                    temps = temperatures[sensor_name]
                    if temps:
                        # Take the highest temperature reading
                        cpu_temp = max(temp.current for temp in temps if temp.current is not None)
                        break
            
            # Look for GPU temperature
            gpu_sensors = ['nouveau', 'radeon', 'amdgpu']
            for sensor_name in gpu_sensors:
                if sensor_name in temperatures:
                    temps = temperatures[sensor_name]
                    if temps:
                        gpu_temp = max(temp.current for temp in temps if temp.current is not None)
                        break
            
            # If no specific sensors found, try any available temperature
            if cpu_temp is None and temperatures:
                all_temps = []
                for sensor_name, temps in temperatures.items():
                    for temp in temps:
                        if temp.current is not None:
                            all_temps.append(temp.current)
                if all_temps:
                    cpu_temp = max(all_temps)  # Use highest as CPU temp
            
            if cpu_temp is not None:
                thermal_data['cpu_temp'] = cpu_temp
            if gpu_temp is not None:
                thermal_data['gpu_temp'] = gpu_temp
                
        except (AttributeError, OSError):
            # sensors_temperatures not available on this platform
            pass
        
        return thermal_data


class ProcessCollector(MetricCollector):
    """Collects process and thread metrics"""
    
    def collect(self) -> Dict:
        try:
            # Count all processes
            all_processes = list(psutil.process_iter())
            process_count = len(all_processes)
            
            # Count all threads
            thread_count = 0
            for proc in all_processes:
                try:
                    thread_count += proc.num_threads()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    # Process may have disappeared or we don't have permission
                    continue
            
            return {
                'count': process_count,
                'thread_count': thread_count
            }
        except Exception as e:
            logger.debug(f"Error collecting process metrics: {e}")
            return {'count': 0, 'thread_count': 0}


class MetricBuffer:
    """Buffer for storing metrics when API is unavailable"""
    
    def __init__(self, max_size=100):
        self.buffer = deque(maxlen=max_size)
        self.lock = threading.Lock()
    
    def add(self, metrics: Dict):
        """Add metrics to buffer"""
        with self.lock:
            self.buffer.append(metrics)
    
    def get_all(self) -> List[Dict]:
        """Get all buffered metrics and clear buffer"""
        with self.lock:
            metrics = list(self.buffer)
            self.buffer.clear()
            return metrics
    
    def size(self) -> int:
        """Get current buffer size"""
        with self.lock:
            return len(self.buffer)


class UptimeSquirrelAgent:
    """Main agent class"""
    
    def __init__(self, config_file: str = '/etc/uptimesquirrel/agent.conf'):
        self.config = self.load_config(config_file)
        self.api_url = self.config.get('api', 'url', fallback='https://agent-api.uptimesquirrel.com')
        self.agent_key = self.config.get('api', 'key', fallback=None)
        self.interval = self.config.getint('monitoring', 'interval', fallback=60)
        self.hostname = socket.gethostname()
        
        # Remote configuration
        self.last_config_check = 0
        self.config_check_interval = 300  # Check every 5 minutes
        self.remote_thresholds = {}
        self.threshold_version = 0  # Track threshold version to avoid unnecessary updates
        logger.info(f"Agent initialized with threshold version: {self.threshold_version}")
        
        # Metric buffering
        self.metric_buffer = MetricBuffer()
        self.consecutive_failures = 0
        self.max_consecutive_failures = 5
        
        # Initialize collectors
        # Always use /etc/uptimesquirrel for disk config
        disk_config_dir = "/etc/uptimesquirrel"
        
        self.collectors = {
            'cpu': CPUCollector(),
            'memory': MemoryCollector(),
            'disk': DiskCollector(config_dir=disk_config_dir),
            'disk_io': DiskIOCollector(),
            'network': NetworkCollector(),
            'services': ServiceCollector(self.get_monitored_services()),
            'sensors': ThermalCollector(),
            'processes': ProcessCollector()
        }
        
        # Initialize SNMP collector if configured
        self._init_snmp_collector()
        
        # Setup HTTP session with retries
        self.session = requests.Session()
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        
        # Configure connection pooling
        adapter = HTTPAdapter(
            pool_connections=1,
            pool_maxsize=1,
            max_retries=retry_strategy
        )
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        
        # Set headers
        self.session.headers.update({
            'User-Agent': f'UptimeSquirrel-Agent/{__version__}',
            'X-Agent-Key': self.agent_key
        })
    
    def load_config(self, config_file: str) -> configparser.ConfigParser:
        """Load configuration from file"""
        config = configparser.ConfigParser()
        
        # Default configuration
        config['api'] = {
            'url': 'https://agent-api.uptimesquirrel.com',
            'key': ''
        }
        config['monitoring'] = {
            'interval': '60',
            'cpu_threshold': '80.0',
            'memory_threshold': '85.0',
            'disk_threshold': '90.0'
        }
        config['services'] = {}
        
        # Load from file if exists
        if os.path.exists(config_file):
            config.read(config_file)
        
        return config
    
    def get_monitored_services(self) -> List[str]:
        """Get list of services to monitor from config"""
        services = []
        if 'services' in self.config:
            for key, value in self.config['services'].items():
                if key.startswith('monitor_') and value.lower() == 'true':
                    service_name = key.replace('monitor_', '')
                    services.append(service_name)
        return services
    
    def _init_snmp_collector(self):
        """Initialize SNMP collector if configured and available"""
        if not SNMP_AVAILABLE:
            logger.info("SNMP support not available - skipping SNMP initialization")
            return
        
        # Load SNMP devices from config
        snmp_devices = []
        config_file = self.config._sections.get('DEFAULT', {}).get('__file__', '/etc/uptimesquirrel/agent.conf')
        
        # Look for SNMP device sections
        for section in self.config.sections():
            if section.startswith('snmp:'):
                try:
                    device_name = section.split(':', 1)[1]
                    logger.info(f"Loading SNMP device configuration: {device_name}")
                    
                    # Get device configuration
                    hostname = self.config.get(section, 'hostname')
                    port = self.config.getint(section, 'port', fallback=161)
                    version = self.config.get(section, 'version', fallback='v2c')
                    
                    # Convert version string to enum
                    version_enum = SNMPVersion(version)
                    
                    # Create device based on version
                    if version_enum in [SNMPVersion.V1, SNMPVersion.V2C]:
                        community = self.config.get(section, 'community', fallback='public')
                        device = SNMPDevice(
                            hostname=hostname,
                            port=port,
                            version=version_enum,
                            community=community,
                            timeout=self.config.getint(section, 'timeout', fallback=5),
                            retries=self.config.getint(section, 'retries', fallback=3)
                        )
                    else:  # v3
                        device = SNMPDevice(
                            hostname=hostname,
                            port=port,
                            version=version_enum,
                            username=self.config.get(section, 'username'),
                            auth_key=self.config.get(section, 'auth_key', fallback=None),
                            priv_key=self.config.get(section, 'priv_key', fallback=None),
                            timeout=self.config.getint(section, 'timeout', fallback=5),
                            retries=self.config.getint(section, 'retries', fallback=3)
                        )
                    
                    snmp_devices.append(device)
                    logger.info(f"Added SNMP device: {device_name} ({hostname}:{port} {version})")
                    
                except Exception as e:
                    logger.error(f"Failed to load SNMP device {section}: {e}")
        
        # Add SNMP collector if devices are configured
        if snmp_devices:
            logger.info(f"Initializing SNMP collector with {len(snmp_devices)} devices")
            self.collectors['snmp'] = SNMPCollector(snmp_devices)
        else:
            logger.info("No SNMP devices configured")
    
    def fetch_remote_config(self):
        """Fetch configuration from server"""
        try:
            response = self.session.get(
                f"{self.api_url}/agent/config",
                timeout=10
            )
            if response.status_code == 200:
                config = response.json()
                logger.info(f"Received config from server: {config}")
                new_version = config.get('threshold_version', 0)
                
                # Only update thresholds if version has changed
                logger.info(f"Config check - current version: {self.threshold_version}, server version: {new_version}")
                if new_version > self.threshold_version:
                    self.remote_thresholds = config.get('thresholds', {})
                    self.threshold_version = new_version
                    logger.info(f"Updated thresholds from server (v{new_version}): {self.remote_thresholds}")
                    logger.info(f"Threshold keys in response: {list(self.remote_thresholds.keys())}")
                else:
                    logger.info(f"Threshold config unchanged (v{new_version}), keeping: {self.remote_thresholds}")
                self.config_check_interval = config.get('check_interval', 300)
            elif response.status_code == 404:
                # Endpoint not implemented yet, ignore
                logger.debug("Remote config endpoint not available")
            else:
                logger.warning(f"Failed to fetch remote config: HTTP {response.status_code}")
        except requests.exceptions.RequestException as e:
            logger.warning(f"Failed to fetch remote config: {e}")
        except Exception as e:
            logger.error(f"Unexpected error fetching remote config: {e}")
    
    def get_threshold(self, metric_type: str, default: float) -> float:
        """Get threshold, preferring remote over local config"""
        # Check remote thresholds first
        if metric_type in self.remote_thresholds:
            threshold = float(self.remote_thresholds[metric_type])
            logger.info(f"Using remote threshold for {metric_type}: {threshold} (from remote_thresholds: {self.remote_thresholds})")
            return threshold
        
        # Fall back to local config
        local_threshold = self.config.getfloat('monitoring', f'{metric_type}_threshold', fallback=default)
        logger.info(f"Using local threshold for {metric_type}: {local_threshold} (remote_thresholds: {self.remote_thresholds})")
        return local_threshold
    
    def register(self):
        """Register agent with API"""
        logger.info(f"Registering agent {self.hostname}")
        
        registration_data = {
            'hostname': self.hostname,
            'agent_version': __version__,
            'platform': platform.platform(),
            'registration_time': int(time.time()),
            'cpu_count': psutil.cpu_count(),
            'total_memory': psutil.virtual_memory().total,
            'disk_paths': [p.mountpoint for p in psutil.disk_partitions()],
            'monitored_services': self.get_monitored_services()
        }
        
        try:
            response = self.session.post(
                f"{self.api_url}/agent/register",
                json=registration_data,
                timeout=30
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"Registration successful: {result.get('message')}")
            return result
        except requests.exceptions.RequestException as e:
            logger.error(f"Registration failed: {e}")
            raise
    
    def collect_metrics(self) -> Dict:
        """Collect all system metrics"""
        logger.debug("Collecting system metrics")
        
        metrics = {
            'hostname': self.hostname,
            'timestamp': int(time.time()),
            'uptime': int(time.time() - psutil.boot_time()),
            'agent_version': __version__,
            'active_thresholds': {
                'cpu': self.get_threshold('cpu', 80.0),
                'memory': self.get_threshold('memory', 85.0),
                'disk': self.get_threshold('disk', 90.0),
                'version': self.threshold_version,
                'source': 'remote' if self.remote_thresholds else 'local'
            }
        }
        
        # Collect from each collector
        for name, collector in self.collectors.items():
            try:
                metrics[name] = collector.collect()
            except Exception as e:
                logger.error(f"Error collecting {name} metrics: {e}")
                metrics[name] = {'error': str(e)}
        
        return metrics
    
    def check_thresholds(self, metrics: Dict) -> List[Dict]:
        """Check if any metrics exceed configured thresholds"""
        alerts = []
        
        # CPU threshold
        cpu_threshold = self.get_threshold('cpu', 80.0)
        cpu_usage = metrics.get('cpu', {}).get('usage_percent', 0)
        logger.debug(f"Checking CPU: usage={cpu_usage:.1f}%, threshold={cpu_threshold}%")
        if cpu_usage > cpu_threshold:
            alerts.append({
                'type': 'cpu_high',
                'message': f'CPU usage is {cpu_usage:.1f}% (threshold: {cpu_threshold}%)',
                'severity': 'warning' if cpu_usage < 90 else 'critical',
                'timestamp': metrics['timestamp'],
                'metadata': {'usage': cpu_usage, 'threshold': cpu_threshold}
            })
        
        # Memory threshold
        memory_threshold = self.get_threshold('memory', 85.0)
        memory_usage = metrics.get('memory', {}).get('percent', 0)
        if memory_usage > memory_threshold:
            alerts.append({
                'type': 'memory_high',
                'message': f'Memory usage is {memory_usage:.1f}% (threshold: {memory_threshold}%)',
                'severity': 'warning' if memory_usage < 95 else 'critical',
                'timestamp': metrics['timestamp'],
                'metadata': {'usage': memory_usage, 'threshold': memory_threshold}
            })
        
        # Disk threshold
        disk_threshold = self.get_threshold('disk', 90.0)
        for mount, disk_data in metrics.get('disk', {}).items():
            disk_usage = disk_data.get('percent', 0)
            if disk_usage > disk_threshold:
                alerts.append({
                    'type': 'disk_high',
                    'message': f'Disk usage on {mount} is {disk_usage:.1f}% (threshold: {disk_threshold}%)',
                    'severity': 'warning' if disk_usage < 95 else 'critical',
                    'timestamp': metrics['timestamp'],
                    'metadata': {'mount': mount, 'usage': disk_usage, 'threshold': disk_threshold}
                })
        
        # Service status
        for service, status in metrics.get('services', {}).items():
            if not status.get('active', False):
                alerts.append({
                    'type': 'service_down',
                    'message': f'Service {service} is not active',
                    'severity': 'critical',
                    'timestamp': metrics['timestamp'],
                    'metadata': {'service': service, 'status': status.get('status')}
                })
        
        # SNMP device status
        snmp_data = metrics.get('snmp', {})
        for device_name, device_data in snmp_data.items():
            # Check if device is unreachable
            if device_data.get('status') == 'unreachable':
                alerts.append({
                    'type': 'snmp_device_unreachable',
                    'message': f'SNMP device {device_name} is unreachable: {device_data.get("error", "Unknown error")}',
                    'severity': 'critical',
                    'timestamp': metrics['timestamp'],
                    'metadata': {'device': device_name, 'error': device_data.get('error')}
                })
                continue
            
            # Check interface status
            interfaces = device_data.get('interfaces', [])
            for interface in interfaces:
                if interface.get('admin_status') == 1 and interface.get('oper_status') != 1:
                    alerts.append({
                        'type': 'snmp_interface_down',
                        'message': f'Interface {interface.get("description")} on {device_name} is down',
                        'severity': 'warning',
                        'timestamp': metrics['timestamp'],
                        'metadata': {
                            'device': device_name,
                            'interface': interface.get('description'),
                            'index': interface.get('index')
                        }
                    })
            
            # Check CPU (if available)
            cpu_data = device_data.get('cpu', {})
            if 'usage_5min' in cpu_data:  # Cisco style
                cpu_usage = cpu_data['usage_5min']
                if cpu_usage > 80:
                    alerts.append({
                        'type': 'snmp_cpu_high',
                        'message': f'CPU usage on {device_name} is {cpu_usage}% (5min avg)',
                        'severity': 'warning' if cpu_usage < 90 else 'critical',
                        'timestamp': metrics['timestamp'],
                        'metadata': {'device': device_name, 'usage': cpu_usage}
                    })
            
            # Check memory (if available)
            memory_data = device_data.get('memory', {})
            if 'percent' in memory_data:
                mem_usage = memory_data['percent']
                if mem_usage > 85:
                    alerts.append({
                        'type': 'snmp_memory_high',
                        'message': f'Memory usage on {device_name} is {mem_usage:.1f}%',
                        'severity': 'warning' if mem_usage < 95 else 'critical',
                        'timestamp': metrics['timestamp'],
                        'metadata': {'device': device_name, 'usage': mem_usage}
                    })
            
            # Check storage (if available)
            storage_list = device_data.get('storage', [])
            for storage in storage_list:
                storage_usage = storage.get('percent', 0)
                if storage_usage > 90:
                    alerts.append({
                        'type': 'snmp_storage_high',
                        'message': f'Storage {storage.get("description")} on {device_name} is {storage_usage:.1f}% full',
                        'severity': 'warning' if storage_usage < 95 else 'critical',
                        'timestamp': metrics['timestamp'],
                        'metadata': {
                            'device': device_name,
                            'storage': storage.get('description'),
                            'usage': storage_usage
                        }
                    })
        
        return alerts
    
    def report_metrics(self, metrics: Dict):
        """Send metrics to API with retry and buffering"""
        try:
            # Debug logging for network metrics
            network_data = metrics.get('network', {})
            if network_data:
                logger.info(f"Sending network metrics: {network_data}")
            else:
                logger.warning("No network data in metrics!")
            
            response = self.session.post(
                f"{self.api_url}/agent/metrics",
                json={
                    'agent_version': __version__,
                    'timestamp': metrics['timestamp'],
                    'metrics': metrics
                },
                timeout=30
            )
            response.raise_for_status()
            
            # Reset failure counter on success
            self.consecutive_failures = 0
            
            # Send any buffered metrics
            if self.metric_buffer.size() > 0:
                logger.info(f"Sending {self.metric_buffer.size()} buffered metrics")
                buffered_metrics = self.metric_buffer.get_all()
                for buffered in buffered_metrics:
                    try:
                        self.session.post(
                            f"{self.api_url}/agent/metrics",
                            json={
                                'agent_version': __version__,
                                'timestamp': buffered['timestamp'],
                                'metrics': buffered
                            },
                            timeout=30
                        )
                    except Exception as e:
                        logger.error(f"Failed to send buffered metric: {e}")
            
            logger.debug(f"Metrics reported successfully")
            
        except requests.exceptions.RequestException as e:
            self.consecutive_failures += 1
            logger.error(f"Failed to report metrics (attempt {self.consecutive_failures}): {e}")
            
            # Buffer metrics for later if we're having issues
            if self.consecutive_failures < self.max_consecutive_failures:
                self.metric_buffer.add(metrics)
                logger.info(f"Buffered metrics for later delivery (buffer size: {self.metric_buffer.size()})")
            else:
                logger.error("Max consecutive failures reached, metrics may be lost")
    
    def send_alerts(self, alerts: List[Dict]):
        """Send alerts to API"""
        for alert in alerts:
            logger.warning(f"Alert: {alert['type']} - {alert['message']}")
            
            try:
                response = self.session.post(
                    f"{self.api_url}/agent/alerts",
                    json=alert,
                    timeout=30
                )
                response.raise_for_status()
                logger.info(f"Alert sent: {alert['type']} - {alert['message']}")
            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to send alert: {e}")
    
    def run_once(self):
        """Run one collection/reporting cycle"""
        try:
            # Check for config updates periodically
            if time.time() - self.last_config_check > self.config_check_interval:
                self.fetch_remote_config()
                self.last_config_check = time.time()
            
            # Collect metrics
            metrics = self.collect_metrics()
            
            # Check thresholds
            alerts = self.check_thresholds(metrics)
            
            # Report metrics
            self.report_metrics(metrics)
            
            # Send any alerts
            if alerts:
                self.send_alerts(alerts)
            
        except Exception as e:
            logger.error(f"Error in collection cycle: {e}")
    
    def run(self):
        """Main agent loop"""
        logger.info(f"Starting UptimeSquirrel Agent v{__version__}")
        logger.info(f"Hostname: {self.hostname}")
        logger.info(f"API URL: {self.api_url}")
        logger.info(f"Reporting interval: {self.interval}s")
        
        # Skip registration - agent is already created via web UI
        # The agent key is provided during installation
        logger.info("Agent initialized with provided key")
        
        # Initial config fetch
        self.fetch_remote_config()
        
        # Log initial threshold state
        logger.info(f"Starting with thresholds - CPU: {self.get_threshold('cpu', 80.0)}%, Memory: {self.get_threshold('memory', 85.0)}%, Disk: {self.get_threshold('disk', 90.0)}%")
        logger.info(f"Threshold source: {'remote' if self.remote_thresholds else 'local config'}")
        
        # Main loop
        while True:
            start_time = time.time()
            
            self.run_once()
            
            # Sleep until next interval
            elapsed = time.time() - start_time
            sleep_time = max(0, self.interval - elapsed)
            if sleep_time > 0:
                logger.debug(f"Sleeping for {sleep_time:.1f}s")
                time.sleep(sleep_time)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='UptimeSquirrel System Monitoring Agent')
    parser.add_argument('-c', '--config', default='/etc/uptimesquirrel/agent.conf',
                        help='Configuration file path')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose logging')
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    parser.add_argument('--test', action='store_true',
                        help='Run once and exit')
    parser.add_argument('--check-update', action='store_true',
                        help='Check for updates')
    parser.add_argument('--status', action='store_true',
                        help='Show current configuration and exit')
    parser.add_argument('install-service', nargs='?', default=None,
                        help='Install systemd service')
    
    args = parser.parse_args()
    
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    # Install systemd service if requested
    if getattr(args, 'install_service', None) is not None:
        import subprocess
        import pkg_resources
        
        service_file = pkg_resources.resource_filename('uptimesquirrel_agent', 'systemd/uptimesquirrel-agent.service')
        
        print("Installing UptimeSquirrel Agent systemd service...")
        
        # Create necessary directories
        os.makedirs('/etc/uptimesquirrel', exist_ok=True)
        os.makedirs('/var/lib/uptimesquirrel', exist_ok=True)
        os.makedirs('/var/log/uptimesquirrel', exist_ok=True)
        
        # Copy service file
        try:
            subprocess.run(['sudo', 'cp', service_file, '/etc/systemd/system/'], check=True)
            subprocess.run(['sudo', 'systemctl', 'daemon-reload'], check=True)
            print("✓ Service file installed")
            
            # Create default config if it doesn't exist
            if not os.path.exists('/etc/uptimesquirrel/agent.conf'):
                print("\nCreating default configuration file...")
                default_config = """[api]
url = https://agent-api.uptimesquirrel.com
key = YOUR_AGENT_KEY_HERE

[agent]
interval = 60
"""
                with open('/etc/uptimesquirrel/agent.conf', 'w') as f:
                    f.write(default_config)
                print("✓ Default configuration created at /etc/uptimesquirrel/agent.conf")
                print("\n⚠️  IMPORTANT: Edit /etc/uptimesquirrel/agent.conf and add your agent key!")
            
            print("\nTo start the service:")
            print("  sudo systemctl start uptimesquirrel-agent")
            print("  sudo systemctl enable uptimesquirrel-agent")
            print("\nTo view logs:")
            print("  sudo journalctl -u uptimesquirrel-agent -f")
            
        except subprocess.CalledProcessError as e:
            print(f"✗ Failed to install service: {e}")
            sys.exit(1)
        
        sys.exit(0)
    
    # Check for updates if requested
    if args.check_update:
        print(f"Current version: {__version__}")
        print("To update, run: sudo /opt/uptimesquirrel/update.sh")
        print("Or manually: sudo curl -sSL https://agent-api.uptimesquirrel.com/agent/update.sh | sudo bash")
        sys.exit(0)
    
    # Show status if requested
    if args.status:
        agent = UptimeSquirrelAgent(args.config)
        agent.fetch_remote_config()  # Get latest config
        print(f"UptimeSquirrel Agent v{__version__} Status")
        print(f"Hostname: {agent.hostname}")
        print(f"API URL: {agent.api_url}")
        print(f"\nCurrent Thresholds:")
        print(f"  CPU: {agent.get_threshold('cpu', 80.0)}%")
        print(f"  Memory: {agent.get_threshold('memory', 85.0)}%")
        print(f"  Disk: {agent.get_threshold('disk', 90.0)}%")
        print(f"\nThreshold Version: {agent.threshold_version}")
        print(f"Source: {'Remote (server)' if agent.remote_thresholds else 'Local (config file)'}")
        if agent.remote_thresholds:
            print(f"Remote thresholds: {agent.remote_thresholds}")
        sys.exit(0)
    
    # Create agent
    agent = UptimeSquirrelAgent(args.config)
    
    if args.test:
        # Test mode - run once
        agent.run_once()
    else:
        # Normal mode - run forever
        try:
            agent.run()
        except KeyboardInterrupt:
            logger.info("Shutting down agent")
            sys.exit(0)
        except Exception as e:
            logger.error(f"Fatal error: {e}")
            sys.exit(1)


if __name__ == '__main__':
    main()
