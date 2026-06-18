# Test Flow Patterns

Visual guides to the most common testing flows in this repository.
Each document shows the resource creation chain, data flow, and how components connect.

## Network Flows

| Flow | Description | Used In |
|------|-------------|---------|
| [VM Creation](VM_CREATION.md) | How VMs are created — factory vs legacy patterns | All domains |
| [Linux Bridge](LINUX_BRIDGE.md) | Secondary network via Linux bridge CNI | `tests/network/l2_bridge/`, `tests/network/connectivity/` |
| [Localnet](LOCALNET.md) | OVN localnet secondary network | `tests/network/localnet/` |
| [SR-IOV](SRIOV.md) | SR-IOV passthrough networking | `tests/network/sriov/` |
| [User Defined Network (UDN)](UDN.md) | Primary network via OVN UDN | `tests/network/user_defined_network/` |
| [Connectivity Testing](CONNECTIVITY_TESTING.md) | Verifying network reachability between VMs | All network tests |
| [Migration](MIGRATION.md) | VM migration with network continuity | `tests/network/migration/`, `tests/network/*/migration_stuntime/` |
| [NIC Hot-Plug](HOT_PLUG.md) | Adding/removing network interfaces at runtime | `tests/network/l2_bridge/` |
| [Cloud-Init Networking](CLOUD_INIT_NETWORKING.md) | Configuring guest network via cloud-init | All network tests |

## General Flows

| Flow | Description |
|------|-------------|
| [Golden Image](GOLDEN_IMAGE.md) | Download-once, clone-many pattern for VM boot disks |
