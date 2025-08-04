# UptimeSquirrel Agent PyPI Package

Official Python package for the UptimeSquirrel system monitoring agent.

## Installation

```bash
pip install uptimesquirrel-agent
```

## Quick Start

1. Install the agent:
```bash
pip install uptimesquirrel-agent
```

2. Create a configuration file at `/etc/uptimesquirrel/agent.conf`:
```ini
[server]
api_url = https://api.uptimesquirrel.com
api_key = YOUR_API_KEY_HERE

[agent]
interval = 60
hostname = auto
```

3. Run the agent:
```bash
uptimesquirrel-agent --config /etc/uptimesquirrel/agent.conf
```

## Systemd Service

For production deployments, install as a systemd service:

```bash
# Create config directory
sudo mkdir -p /etc/uptimesquirrel

# Copy configuration
sudo cp agent.conf /etc/uptimesquirrel/

# Install systemd service
sudo cp ~/.local/lib/python*/site-packages/uptimesquirrel_agent/systemd/uptimesquirrel-agent.service /etc/systemd/system/

# Enable and start service
sudo systemctl enable uptimesquirrel-agent
sudo systemctl start uptimesquirrel-agent
```

## Features

- System metrics collection (CPU, memory, disk, network)
- Disk I/O monitoring
- Process and thread counting
- Network bandwidth monitoring
- Temperature/thermal data (where available)
- Automatic reconnection and retry logic
- Local metric buffering for offline scenarios
- Remote threshold configuration

## Requirements

- Python 3.7 or higher
- Linux operating system
- Root/sudo access for systemd service installation

## Documentation

Full documentation available at: https://docs.uptimesquirrel.com/agent

## Support

- GitHub Issues: https://github.com/Scripted-Ventures-NZ/uptimesquirrel-agent-pypi/issues
- Email: support@uptimesquirrel.com

## License

MIT License - see LICENSE file for details.