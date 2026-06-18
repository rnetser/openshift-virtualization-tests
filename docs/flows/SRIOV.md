# SR-IOV Flow

SR-IOV (Single Root I/O Virtualization) passes a physical NIC's virtual function (VF) directly to the VM, bypassing the host network stack for high performance.

```mermaid
flowchart TD
    subgraph Operator Setup
        A[SR-IOV Operator installed] --> B[SriovNetworkNodePolicy]
        B --> C[Allocates VFs on physical NIC]
    end

    subgraph Network Definition
        D[network_nad with type=sriov] --> E[SriovNetwork + NAD]
        E --> F[References SR-IOV resource name]
    end

    subgraph VM Creation
        G[sriov_vm helper] --> H[VirtualMachineForTests]
        H --> I[interfaces_types: sriov]
        I --> J[MAC address assigned explicitly]
        J --> K[cloud-init with MAC-matched static IP]
    end

    C --> E
    F --> H
```

## Resource Chain

```mermaid
flowchart LR
    Policy[SriovNetworkNodePolicy<br>allocates VFs] --> VF[Virtual Functions<br>on physical NIC]
    SriovNet[SriovNetwork<br>+ NAD] --> VM[VM<br>SR-IOV interface]
    VF --> VM
```

## Key Pattern: MAC-Based Cloud-Init

SR-IOV VMs use explicit MAC addresses and match them in cloud-init network data:

```yaml
ethernets:
  "1":
    match:
      macaddress: "02:00:b5:b5:b5:01"
    addresses: ["10.200.0.1/24"]
```

This ensures the correct interface gets the correct IP regardless of device naming.
