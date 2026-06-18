# Localnet Flow

Localnet connects VMs to physical networks through OVN's external bridge (`br-ex`). Unlike Linux bridge, it uses OVN bridge mappings instead of a separate bridge device.

```mermaid
flowchart TD
    subgraph OVN Configuration
        A[NNCP with OVN bridge mapping] --> B[Maps physical network name to br-ex]
        B --> C[Optional: VLAN configuration]
    end

    subgraph Network Definition
        D[ClusterUserDefinedNetwork CUDN] --> E[Localnet topology]
        E --> F[References physical network name]
        F --> G[Namespace selector via labels]
    end

    subgraph Namespace Setup
        H[Create namespace] --> I[Label matching CUDN selector e.g. test: localnet]
        I --> J[CUDN matches namespace by label]
    end

    subgraph VM Creation
        K[localnet_vm helper] --> L[base_vmspec + interfaces]
        L --> M[Cloud-init with static IPs]
        M --> N[Anti-affinity ensures VMs on different nodes]
    end

    C --> F
    J --> K
```

## Resource Chain

```mermaid
flowchart LR
    NNCP[NNCP<br>OVN bridge mapping] --> BrEx[br-ex<br>OVN external bridge]
    CUDN[CUDN<br>localnet topology] --> NS[Namespace<br>label-selected]
    BrEx --> VM[VM<br>localnet interface]
    NS --> VM
```

## Key Differences from Linux Bridge

| Aspect | Linux Bridge | Localnet |
|--------|-------------|----------|
| Bridge type | Linux bridge (host) | OVN br-ex |
| Network definition | NAD | ClusterUserDefinedNetwork (CUDN) |
| Namespace coupling | NAD in namespace | CUDN selects namespaces by custom labels e.g. `test: localnet` |
| VLAN config | On NAD | On CUDN (access mode) |
| Node config | NNCP creates bridge | NNCP maps physical net to br-ex |
| IPAM | Manual (cloud-init) | Optional (CUDN can disable or enable) |
