# Network Migration Testing Flow

Migration tests verify that VM network connectivity survives live migration to a different node.

```mermaid
flowchart TD
    subgraph Setup
        A[Create bridge on worker-1 + worker-2] --> B[Create NAD]
        B --> C[Create migrating VM on worker-1]
        C --> D[Create peer VM on worker-2]
        D --> E[Verify connectivity migrating VM ↔ peer VM]
    end

    subgraph Migration
        F[migrate_vm_and_verify migrating VM] --> G[migrating VM moves to worker-2]
        G --> H[Verify connectivity still works]
    end

    subgraph Stuntime Measurement
        I[Start ContinuousPing] --> J[Trigger migration]
        J --> K[Stop ping, measure downtime]
        K --> L{Downtime < threshold?}
    end

    E --> F
    E --> I
```

## Bridge Must Exist on Both Nodes

```mermaid
flowchart LR
    Worker1[Worker-1<br>bridge-migration] --> NAD[NAD<br>references bridge]
    Worker2[Worker-2<br>bridge-migration] --> NAD
    NAD --> VM[VM migrates<br>between workers]
```

The bridge NNCP must target all worker nodes (not just one), otherwise migration fails because the destination node has no matching bridge.

## Key Utilities

- `migrate_vm_and_verify(vm)` — triggers migration and waits for completion
- `assert_ping_successful(src_vm, dst_ip)` — verifies connectivity post-migration
- `ContinuousPing` — measures downtime during migration

## Other Migration Variants

Migration testing is not limited to Linux bridge networks. The same `ContinuousPing` / stuntime measurement pattern is reused across network types:

- **Localnet migration** — `tests/network/localnet/migration_stuntime/` validates that VMs on localnet (OVN) networks maintain connectivity through live migration, using the same downtime-threshold approach.
