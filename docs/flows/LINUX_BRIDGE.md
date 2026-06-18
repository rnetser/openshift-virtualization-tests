# Linux Bridge Flow

This is the most common secondary network pattern. A Linux bridge is created on the host nodes, then a NAD (NetworkAttachmentDefinition) references it, and VMs attach to it.

```mermaid
flowchart TD
    subgraph Node Setup
        A[network_device utility] --> B[NodeNetworkConfigurationPolicy NNCP]
        B --> C[Linux bridge on worker nodes]
        C --> D[Bridge connects to physical NIC port]
    end

    subgraph Network Definition
        E[network_nad utility] --> F[NetworkAttachmentDefinition NAD]
        F --> G[References bridge name + VLAN if needed]
    end

    subgraph VM Creation
        H[VirtualMachineForTests or fedora_vm] --> I[VM with secondary interface]
        I --> J[cloud-init assigns static IP to eth1]
        J --> K[VM starts + waits for agent]
    end

    D --> F
    G --> I
```

## Resource Chain

```mermaid
flowchart LR
    NNCP[NNCP<br>creates bridge on nodes] --> Bridge[Linux Bridge<br>on host]
    Bridge --> NAD[NAD<br>references bridge]
    NAD --> VM1[VM-A eth1<br>bridge interface]
    NAD --> VM2[VM-B eth1<br>bridge interface]
    VM1 <--> |L2 connectivity| VM2
```

## Typical Fixture Stack

```mermaid
flowchart TD
    hosts_common_available_ports --> network_device
    network_device --> bridge_on_workers[Linux bridge NNCP]
    bridge_on_workers --> network_nad[NAD referencing bridge]
    network_nad --> vm_with_bridge[VM with secondary bridge interface]
    vm_with_bridge --> connectivity_test[Ping / TCP between VMs]
```

## Primary + Secondary Topology

The dominant VM pattern uses **masquerade** for the primary (pod network) interface and a **bridge** for the secondary interface. This is the `secondary_network_vm()` helper in `tests/network/l2_bridge/libl2bridge.py`.

```mermaid
flowchart TD
    subgraph VM Network Interfaces
        VM[VM] --> ETH0[eth0: masquerade — pod network]
        VM --> ETH1[eth1: bridge — via NAD, static IP]
    end

    subgraph Configuration
        A[base_vmspec] --> B[Interface: default/masquerade + secondary/bridge]
        B --> C[Network: pod + multus NAD]
        C --> D[cloud-init configures eth0 + eth1]
    end
```

- **eth0** (masquerade): Provides default pod network connectivity.
- **eth1** (bridge): Attaches to the Linux bridge via a NAD. Cloud-init assigns a static CIDR address.
- Cloud-init renders both interfaces via `cloudinit.NetworkData(ethernets={...})`.

## VLAN Support

When VLAN tagging is needed, the NAD includes a VLAN ID. The bridge carries tagged traffic and the VM sees untagged frames on its interface.
