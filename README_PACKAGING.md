# UptimeSquirrel Agent PyPI Package

This directory contains the PyPI package structure for the UptimeSquirrel Linux agent.

## What's Been Created

1. **Package Structure**:
   - `uptimesquirrel_agent/` - Main package directory
   - `uptimesquirrel_agent/agent.py` - The agent code (copied from frontend)
   - `uptimesquirrel_agent/systemd/` - Contains systemd service file
   - `setup.py` and `pyproject.toml` - Package configuration
   - `README.md` - User-facing documentation
   - `PUBLISHING.md` - Instructions for publishing to PyPI

2. **Key Features Added**:
   - `pip install uptimesquirrel-agent` support
   - `uptimesquirrel-agent install-service` command for easy systemd setup
   - Proper package metadata and dependencies
   - Optional SNMP support via extras

3. **Installation Flow**:
   ```bash
   # Install the agent
   pip install uptimesquirrel-agent
   
   # Install as a systemd service
   sudo uptimesquirrel-agent install-service
   
   # Configure the agent
   sudo nano /etc/uptimesquirrel/agent.conf
   
   # Start the service
   sudo systemctl start uptimesquirrel-agent
   sudo systemctl enable uptimesquirrel-agent
   ```

## Next Steps

1. **Create PyPI Account**:
   - Register at https://pypi.org
   - Get API token for authentication

2. **Build and Test**:
   ```bash
   cd uptimesquirrel-agent-pypi
   ./build-and-publish.sh
   ```

3. **Publish to PyPI**:
   - Follow instructions in PUBLISHING.md
   - Test on TestPyPI first

4. **Update Documentation**:
   - Update main docs to reference pip installation
   - Update agent installation scripts

## Important Notes

- The agent code is copied from the frontend, so updates need to be synced
- Version number is currently 1.2.7 (matches current Linux agent)
- The package name is `uptimesquirrel-agent` (with hyphen)
- The module name is `uptimesquirrel_agent` (with underscore)