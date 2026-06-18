# Test Flow Patterns

Visual guides to the most common testing flows in this repository.
Each document shows the resource creation chain, data flow, and how components connect.

## General Flows

| Flow | Description | Used In |
|------|-------------|---------|
| [VM Creation](VM_CREATION.md) | VM from template, factory, and legacy patterns | All domains |
| [Golden Image](GOLDEN_IMAGE.md) | Download-once, clone-many pattern for VM boot disks | All domains |
| [Migration](MIGRATION.md) | VM live migration with optional connectivity checks | `tests/virt/`, `tests/storage/`, `tests/network/`, `tests/infrastructure/` |

## Network Flows

| Flow | Description | Used In |
|------|-------------|---------|
| [Linux Bridge](LINUX_BRIDGE.md) | Secondary network via Linux bridge CNI | `tests/network/l2_bridge/`, `tests/network/connectivity/` |
| [Localnet](LOCALNET.md) | OVN localnet secondary network | `tests/network/localnet/` |
| [SR-IOV](SRIOV.md) | SR-IOV passthrough networking | `tests/network/sriov/` |
| [User Defined Network (UDN)](UDN.md) | Primary network via OVN UDN | `tests/network/user_defined_network/` |
| [Connectivity Testing](CONNECTIVITY_TESTING.md) | Verifying network reachability between VMs | All network tests |
| [NIC Hot-Plug](HOT_PLUG.md) | Adding/removing network interfaces at runtime | `tests/network/l2_bridge/` |
| [Cloud-Init Networking](CLOUD_INIT_NETWORKING.md) | Configuring guest network via cloud-init | All network tests |
