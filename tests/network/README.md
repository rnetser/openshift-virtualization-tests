# Network Tests

This directory contains network-related tests for OpenShift Virtualization.

## Test Categories

- **connectivity**: Basic VM connectivity tests
- **hotplug**: Network interface hotplug tests
- **ipv6**: IPv6 networking tests
- **l2_bridge**: L2 bridge networking tests
- **sriov**: SR-IOV networking tests
- **vlan**: VLAN networking tests

## Running Tests

```bash
uv run pytest tests/network/ -m "network"
```
