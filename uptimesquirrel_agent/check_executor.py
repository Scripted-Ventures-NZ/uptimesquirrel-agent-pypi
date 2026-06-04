"""
Check execution module for UptimeSquirrel agent
Handles execution of checks received from the agent-api
"""
import asyncio
import aiohttp
import socket
import time
import json
import subprocess
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from abc import ABC, abstractmethod
import ssl
import certifi

logger = logging.getLogger('uptimesquirrel-agent.executor')


class CheckExecutor(ABC):
    """Base class for check executors"""
    
    @abstractmethod
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute check and return result"""
        pass
        
    @property
    @abstractmethod
    def check_type(self) -> str:
        """Return check type this executor handles"""
        pass


class HTTPExecutor(CheckExecutor):
    """HTTP/HTTPS check executor with detailed timing"""
    
    @property
    def check_type(self) -> str:
        return "HTTP"  # Matches CheckType.HTTP enum
    
    def handles(self, check_type: str) -> bool:
        """Check if this executor handles the given check type"""
        return check_type.upper() in ["HTTP", "HTTPS"]
        
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute HTTP check with timing measurements"""
        result = {
            'started_at': datetime.utcnow().isoformat(),
            'ok': False
        }
        
        url = params.get('url')
        method = params.get('method', 'GET')
        headers = params.get('headers', {})
        timeout_ms = params.get('timeout_ms', 10000)
        skip_ssl = params.get('skip_ssl_verify', False)
        expected_string = params.get('expected_string')
        expected_status = params.get('expected_status', [])
        
        # Timing collectors
        timings = {}
        
        # Create trace to capture timing
        trace_config = aiohttp.TraceConfig()
        
        async def on_request_start(session, context, params):
            context.start = time.time()
            timings['request_start'] = context.start
            
        async def on_dns_resolvehost_start(session, context, params):
            context.dns_start = time.time()
            
        async def on_dns_resolvehost_end(session, context, params):
            if hasattr(context, 'dns_start'):
                timings['dns_ms'] = (time.time() - context.dns_start) * 1000
                
        async def on_connection_create_start(session, context, params):
            context.conn_start = time.time()
            
        async def on_connection_create_end(session, context, params):
            if hasattr(context, 'conn_start'):
                timings['tcp_ms'] = (time.time() - context.conn_start) * 1000
                
        trace_config.on_request_start.append(on_request_start)
        trace_config.on_dns_resolvehost_start.append(on_dns_resolvehost_start)
        trace_config.on_dns_resolvehost_end.append(on_dns_resolvehost_end)
        trace_config.on_connection_create_start.append(on_connection_create_start)
        trace_config.on_connection_create_end.append(on_connection_create_end)
        
        async def on_response_chunk_received(session, context, params):
            # First chunk received = TTFB
            if 'ttfb_ms' not in timings and 'request_start' in timings:
                timings['ttfb_ms'] = (time.time() - timings['request_start']) * 1000
                
        trace_config.on_response_chunk_received.append(on_response_chunk_received)
        
        # SSL configuration
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        if skip_ssl:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
        # Create session with tracing
        timeout = aiohttp.ClientTimeout(total=timeout_ms/1000)
        connector = aiohttp.TCPConnector(ssl=ssl_context, limit=0, force_close=True)
        
        # Add User-Agent header
        if 'User-Agent' not in headers:
            headers['User-Agent'] = 'UptimeSquirrel-Agent/2.0 (+https://uptimesquirrel.com)'
        
        async with aiohttp.ClientSession(
            trace_configs=[trace_config],
            timeout=timeout,
            connector=connector,
            auto_decompress=True  # Ensure gzip/deflate decompression is enabled
        ) as session:
            try:
                tls_start = None
                if url.startswith('https://'):
                    tls_start = time.time()
                    
                async with session.request(
                    method=method,
                    url=url,
                    headers=headers
                ) as response:
                    # Calculate TLS time if HTTPS
                    if tls_start and 'tcp_ms' in timings:
                        timings['tls_ms'] = (time.time() - tls_start) * 1000 - timings['tcp_ms']
                        
                    result['status_code'] = response.status
                    
                    # Check if status code matches expected
                    if expected_status:
                        result['ok'] = response.status in expected_status
                        if not result['ok']:
                            result['error_message'] = f"Status code {response.status} not in expected {expected_status}"
                    else:
                        # Default: 2xx and 3xx are success
                        result['ok'] = 200 <= response.status < 400
                    
                    # Read limited body
                    body = await response.text()
                    result['body_excerpt'] = body[:8192] if body else ""
                    
                    # Check for expected string if provided
                    if expected_string:
                        result['content_matched'] = expected_string in body
                        if not result['content_matched']:
                            result['ok'] = False
                            result['error_message'] = f"Expected string '{expected_string}' not found in response body"
                            # Log for debugging
                            logger.info(f"Content matching failed. Looking for: '{expected_string}', Body length: {len(body)}, Body preview: {body[:200] if body else 'empty'}")
                    
                    # Add detailed error for non-OK status codes
                    if not result['ok'] and not result.get('error_message'):
                        if response.status >= 500:
                            result['error_message'] = f"Server error: HTTP {response.status} - {response.reason}"
                        elif response.status >= 400:
                            result['error_message'] = f"Client error: HTTP {response.status} - {response.reason}"
                        elif response.status >= 300:
                            result['error_message'] = f"Unexpected redirect: HTTP {response.status}"
                    
                    # Extract SSL certificate info for HTTPS
                    if url.startswith('https://'):
                        try:
                            if response.connection and response.connection.transport:
                                ssl_object = response.connection.transport.get_extra_info('ssl_object')
                                if ssl_object:
                                    # Try to get cert even when not verifying
                                    cert = ssl_object.getpeercert()
                                    if not cert:
                                        # When skip_ssl is True, we need to get cert differently
                                        import ssl as ssl_module
                                        der_cert = ssl_object.getpeercert(binary_form=True)
                                        if der_cert:
                                            # Decode DER certificate to get expiry
                                            import cryptography.x509
                                            from cryptography.hazmat.backends import default_backend
                                            # datetime is already imported at module level
                                            x509_cert = cryptography.x509.load_der_x509_certificate(der_cert, default_backend())
                                            not_after = x509_cert.not_valid_after
                                            days_until_expiry = (not_after - datetime.utcnow()).days
                                            
                                            # Check if cert is self-signed
                                            is_self_signed = x509_cert.issuer == x509_cert.subject
                                            
                                            result['ssl_valid'] = not is_self_signed
                                            result['ssl_expiry_days'] = days_until_expiry
                                            result['ssl_self_signed'] = is_self_signed
                                    elif cert:
                                        # Regular cert extraction when verification is enabled
                                        not_after = datetime.strptime(cert['notAfter'], '%b %d %H:%M:%S %Y %Z')
                                        days_until_expiry = (not_after - datetime.utcnow()).days
                                        result['ssl_valid'] = True
                                        result['ssl_expiry_days'] = days_until_expiry
                        except ImportError:
                            # If cryptography is not installed, fall back to basic info
                            result['ssl_valid'] = not skip_ssl  # Valid if we verified, unknown if not
                            logger.debug("cryptography module not available for cert parsing")
                        except Exception as e:
                            logger.debug(f"SSL cert extraction failed: {e}")
                            result['ssl_valid'] = not skip_ssl  # Valid if we verified, unknown if not
                    
                    # Get resolved IP
                    if response.connection and response.connection.transport:
                        peername = response.connection.transport.get_extra_info('peername')
                        if peername:
                            result['ip'] = peername[0]
                            
            except asyncio.TimeoutError:
                result['error_message'] = f"Request timeout after {timeout_ms}ms"
            except aiohttp.ClientConnectorError as e:
                if 'Cannot connect to host' in str(e):
                    result['error_message'] = f"Connection failed: Unable to connect to {url} - {str(e)}"
                elif 'certificate verify failed' in str(e).lower():
                    result['error_message'] = f"SSL certificate verification failed: {str(e)}"
                else:
                    result['error_message'] = f"Connection error: {str(e)}"
            except aiohttp.ClientError as e:
                result['error_message'] = f"HTTP client error: {str(e)}"
            except Exception as e:
                result['error_message'] = f"Unexpected error during HTTP check: {type(e).__name__}: {str(e)}"
                logger.error(f"HTTP check error for {url}: {e}", exc_info=True)
                
        result['finished_at'] = datetime.utcnow().isoformat()
        
        # Calculate total latency
        start = datetime.fromisoformat(result['started_at'])
        end = datetime.fromisoformat(result['finished_at'])
        result['latency_ms'] = (end - start).total_seconds() * 1000
        
        # Add timing details
        result.update(timings)
        
        return result


class TCPExecutor(CheckExecutor):
    """TCP port check executor"""
    
    @property
    def check_type(self) -> str:
        return "TCP"
        
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute TCP port check"""
        result = {
            'started_at': datetime.utcnow().isoformat(),
            'ok': False
        }
        
        host = params.get('host')
        port = params.get('port')
        timeout_ms = params.get('timeout_ms', 5000)
        
        try:
            # Create socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout_ms / 1000)
            
            # Attempt connection
            start_time = time.time()
            sock.connect((host, port))
            connect_time = (time.time() - start_time) * 1000
            
            sock.close()
            
            result['ok'] = True
            result['latency_ms'] = connect_time
            
        except socket.timeout:
            result['error_message'] = f"TCP connection timeout to {host}:{port} after {timeout_ms}ms"
        except socket.gaierror as e:
            result['error_message'] = f"DNS resolution failed for {host}: {str(e)}"
        except ConnectionRefusedError:
            result['error_message'] = f"Connection refused to {host}:{port} - Service may be down"
        except OSError as e:
            if 'No route to host' in str(e):
                result['error_message'] = f"No route to host {host} - Network unreachable"
            else:
                result['error_message'] = f"Network error connecting to {host}:{port}: {str(e)}"
        except Exception as e:
            result['error_message'] = f"Unexpected error during TCP check: {type(e).__name__}: {str(e)}"
            logger.error(f"TCP check error for {host}:{port}: {e}", exc_info=True)
            
        result['finished_at'] = datetime.utcnow().isoformat()
        
        if 'latency_ms' not in result:
            start = datetime.fromisoformat(result['started_at'])
            end = datetime.fromisoformat(result['finished_at'])
            result['latency_ms'] = (end - start).total_seconds() * 1000
            
        return result


class ICMPExecutor(CheckExecutor):
    """ICMP/Ping check executor"""
    
    @property
    def check_type(self) -> str:
        return "PING"  # Matches CheckType.PING enum
        
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute ICMP ping check"""
        result = {
            'started_at': datetime.utcnow().isoformat(),
            'ok': False
        }
        
        host = params.get('host')
        count = params.get('count', 3)
        timeout_ms = params.get('timeout_ms', 5000)
        
        try:
            # Use system ping command with platform-specific flags
            import platform
            import re

            system = platform.system()

            if system == 'Windows':
                # Windows ping: -n count, -w timeout (in ms)
                # Note: Windows doesn't have quiet mode
                # Windows ping already sends back-to-back (no per-packet 1s wait by default),
                # so reported avg from "Average = Xms" reflects actual RTT.
                cmd = ['ping', '-n', str(count), '-w', str(timeout_ms), host]
            else:
                # macOS/Linux ping: -c count, -W timeout (seconds for most, ms for macOS with some versions)
                # Convert timeout to seconds for compatibility
                timeout_sec = max(1, timeout_ms // 1000)
                # -i 0.2 — send packets every 0.2s instead of the default 1s.
                # Without this, "-c 3" takes ~3 seconds of wall-clock time, and if RTT
                # parsing ever falls back to wall time the result is wildly inflated
                # (~3000ms for sub-millisecond LAN targets). 0.2s is the minimum
                # interval permitted for non-root users on both macOS and Linux.
                # We still send 3 packets to keep the reliability/packet-loss signal.
                cmd = ['ping', '-c', str(count), '-i', '0.2', '-W', str(timeout_sec), host]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                # Parse ping output for stats
                output = stdout.decode()

                # Extract packet loss (works for both Windows and Unix)
                loss_match = re.search(r'(\d+\.?\d*)%.*loss', output, re.IGNORECASE)
                if loss_match:
                    packet_loss = float(loss_match.group(1))
                    result['packet_loss'] = packet_loss

                # Extract RTT stats - different formats for Windows vs Unix
                if system == 'Windows':
                    # Windows format: "Minimum = 1ms, Maximum = 3ms, Average = 2ms"
                    avg_match = re.search(r'Average = (\d+)ms', output, re.IGNORECASE)
                    min_match = re.search(r'Minimum = (\d+)ms', output, re.IGNORECASE)
                    max_match = re.search(r'Maximum = (\d+)ms', output, re.IGNORECASE)

                    if avg_match:
                        result['avg_ms'] = float(avg_match.group(1))
                        result['latency_ms'] = result['avg_ms']
                    if min_match:
                        result['min_ms'] = float(min_match.group(1))
                    if max_match:
                        result['max_ms'] = float(max_match.group(1))
                else:
                    # Unix format varies by OS:
                    #   Linux (iputils):  "rtt min/avg/max/mdev = 1.0/2.0/3.0/0.5 ms"
                    #   macOS / BSD:      "round-trip min/avg/max/stddev = 1.0/2.0/3.0/0.5 ms"
                    # The 4th component is mdev on Linux, stddev on macOS. (?:/\w+)?
                    # makes the suffix label-agnostic so both forms parse.
                    rtt_match = re.search(r'min/avg/max(?:/\w+)?\s*=\s*([\d.]+)/([\d.]+)/([\d.]+)', output)
                    if rtt_match:
                        result['min_ms'] = float(rtt_match.group(1))
                        result['avg_ms'] = float(rtt_match.group(2))
                        result['max_ms'] = float(rtt_match.group(3))
                        result['latency_ms'] = result['avg_ms']

                result['ok'] = True
            else:
                # Ping failed - check stderr for details
                error_output = stderr.decode().strip()
                if 'cannot resolve' in error_output.lower() or 'unknown host' in error_output.lower():
                    result['error_message'] = f"DNS resolution failed: Cannot resolve hostname '{host}'"
                elif 'no answer' in error_output.lower():
                    result['error_message'] = f"Ping failed: No response from {host} (100% packet loss)"
                elif 'destination host unreachable' in error_output.lower():
                    result['error_message'] = f"Destination unreachable: Host {host} is not reachable"
                elif 'network is unreachable' in error_output.lower():
                    result['error_message'] = f"Network unreachable: Cannot reach network for {host}"
                else:
                    result['error_message'] = f"Ping failed to {host}: {error_output if error_output else 'No response received'}"
                    
        except asyncio.TimeoutError:
            result['error_message'] = f"Ping command timeout after {timeout_ms}ms"
        except FileNotFoundError:
            result['error_message'] = "Ping command not found on system"
        except Exception as e:
            result['error_message'] = f"Unexpected error during ping check: {type(e).__name__}: {str(e)}"
            logger.error(f"Ping check error for {host}: {e}", exc_info=True)
            
        result['finished_at'] = datetime.utcnow().isoformat()

        # If we never parsed an actual RTT, do NOT fall back to subprocess wall time —
        # that produced bogus ~3000ms values (subprocess duration, not RTT).
        # Leave latency_ms unset and log so we can spot parser regressions.
        if 'latency_ms' not in result:
            logger.warning(
                f"Ping for {host} produced no parseable RTT; omitting latency_ms "
                f"to avoid reporting subprocess wall time as round-trip."
            )

        return result


class ExecutorRegistry:
    """Registry for check executors"""
    
    def __init__(self):
        self.executors = {}
        self._register_default_executors()
        
    def _register_default_executors(self):
        """Register built-in executors"""
        http_executor = HTTPExecutor()
        self.executors['HTTP'] = http_executor
        self.executors['HTTPS'] = http_executor  # Same executor handles both
        self.executors['EXPECTED_STRING'] = http_executor  # EXPECTED_STRING is HTTP with content matching
        self.executors['TCP'] = TCPExecutor()
        self.executors['PING'] = ICMPExecutor()
        
    def get(self, check_type: str) -> Optional[CheckExecutor]:
        """Get executor for check type"""
        return self.executors.get(check_type.upper())
        
    def register(self, check_type: str, executor: CheckExecutor):
        """Register custom executor"""
        self.executors[check_type.upper()] = executor