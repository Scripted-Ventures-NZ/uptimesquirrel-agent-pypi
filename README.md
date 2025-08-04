# UptimeSquirrel Agent

The UptimeSquirrel Agent is a lightweight system monitoring agent that collects and reports system metrics to the UptimeSquirrel monitoring platform.

## Features

- **System Metrics**: CPU, memory, disk, and network usage monitoring
- **Service Monitoring**: Track the status of system services
- **SNMP Support**: Monitor network devices via SNMP (optional)
- **Low Resource Usage**: Minimal CPU and memory footprint
- **Automatic Updates**: Self-updating capability
- **Offline Buffering**: Stores metrics locally when connection is lost

## Installation

### Install via pip

```bash
pip install uptimesquirrel-agent
```

### Configure the agent

Create a configuration file at `/etc/uptimesquirrel/agent.conf`:

```ini
[api]
url = https://agent-api.uptimesquirrel.com
key = YOUR_AGENT_KEY_HERE

[agent]
interval = 60
```

### Run as a service (systemd)

```bash
# Create systemd service
sudo uptimesquirrel-agent install-service

# Start the service
sudo systemctl start uptimesquirrel-agent
sudo systemctl enable uptimesquirrel-agent
```

### Run manually

```bash
uptimesquirrel-agent --config /etc/uptimesquirrel/agent.conf
```

## Configuration Options

### Basic Configuration

- `api.url`: The UptimeSquirrel API endpoint (default: https://agent-api.uptimesquirrel.com)
- `api.key`: Your agent API key (required)
- `agent.interval`: Metrics collection interval in seconds (default: 60)

### Advanced Configuration

- `agent.hostname`: Override automatic hostname detection
- `agent.log_level`: Set logging level (DEBUG, INFO, WARNING, ERROR)
- `agent.buffer_size`: Number of metrics to buffer when offline (default: 100)

### SNMP Configuration (Optional)

To monitor SNMP devices, install with SNMP support:

```bash
pip install uptimesquirrel-agent[snmp]
```

Then add SNMP devices to your configuration:

```ini
[snmp]
devices = router,switch

[snmp:router]
host = 192.168.1.1
community = public
version = 2c

[snmp:switch]
host = 192.168.1.2
community = public
version = 2c
```

## Metrics Collected

- **CPU**: Usage percentage, load average, core count
- **Memory**: Total, used, free, percentage
- **Disk**: Usage per disk, I/O statistics
- **Network**: Bytes/packets sent/received, errors
- **Services**: Status of system services
- **Processes**: Count and resource usage
- **Temperature**: CPU/GPU temperature (if available)

## Requirements

- Python 3.7 or higher
- Linux operating system
- Root/sudo access for service installation

## Support

- Documentation: https://docs.uptimesquirrel.com/agent
- Issues: https://github.com/uptimesquirrel/agent/issues
- Email: support@uptimesquirrel.com

## License

MIT License - see LICENSE file for details