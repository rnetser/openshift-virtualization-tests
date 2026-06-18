# User Defined Network (UDN) Flow

UDN provides a **primary** network for VMs using OVN-Kubernetes L2 bridge plugin. Unlike secondary networks (Linux bridge, localnet), UDN replaces the default pod network.

```mermaid
flowchart TD
    subgraph Namespace Setup
        A[Create namespace] --> B[Label: k8s.ovn.org/primary-user-defined-network]
    end

    subgraph Network Definition
        C[Layer2UserDefinedNetwork] --> D[Role: Primary]
        D --> E[Subnet: auto-generated /24]
        E --> F[IPAM: Persistent lifecycle]
        F --> G[Wait for NetworkAllocationSucceeded]
    end

    subgraph VM Creation
        H[udn_vm helper] --> I[base_vmspec]
        I --> J[udn_primary_network binding=l2bridge]
        J --> K[Sets Interface + Network explicitly]
        K --> L[fedora_vm creates the VM]
    end

    B --> C
    G --> H
```

## Resource Chain

```mermaid
flowchart LR
    NS[Namespace<br>with UDN label] --> UDN[Layer2UserDefinedNetwork<br>primary role]
    UDN --> VM1[client VM<br>UDN primary interface]
    UDN --> VM2[server VM<br>UDN primary interface]
    VM1 <-->|L2 connectivity| VM2
```

## VM Network Configuration

The `udn_vm()` helper in `tests/network/libs/vm_factory.py` explicitly configures the UDN interface:

1. Creates a `base_vmspec()`
2. Calls `udn_primary_network(name="udn-primary", binding=binding)` → returns `(Interface, Network)`
3. Sets `spec.template.spec.domain.devices.interfaces = [iface]`
4. Sets `spec.template.spec.networks = [network]`
5. Creates the VM via `fedora_vm()`

The `binding` parameter controls the network binding:
- `"l2bridge"` — the default for most UDN tests
- `"passt"` — used for passt-binding variant tests

> **Note:** The namespace must carry the label `k8s.ovn.org/primary-user-defined-network: ""` (set via `create_udn_namespace()`).

## Affinity Patterns

UDN tests commonly use anti-affinity to ensure VMs land on different nodes, validating cross-node L2 connectivity. Template labels are passed to `udn_vm()`, which uses the first label as the anti-affinity key:

```python
template_labels = {"udn-test": "true"}
vm = udn_vm(..., template_labels=template_labels)
```
