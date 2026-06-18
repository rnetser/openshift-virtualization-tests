# VM Live Migration

Migration tests verify that a VM can be live-migrated to a different node while preserving state, storage, and (optionally) network connectivity.

> **Repo-wide pattern.** Migration is tested across:
> `tests/virt/node/migration_and_maintenance/`, `tests/storage/`, `tests/network/migration/`, `tests/infrastructure/`

```mermaid
flowchart TD
    A[Running VM on node-1] --> B[migrate_vm_and_verify]
    B --> C[Creates VirtualMachineInstanceMigration resource]
    C --> D[KubeVirt migrates VM to another node]
    D --> E[Wait for migration success]
    E --> F[Optionally wait for network interfaces]
    F --> G[Optionally check SSH connectivity]
```

## Key Utility

`migrate_vm_and_verify(vm)` from `utilities/virt.py`:
- Creates a `VirtualMachineInstanceMigration` resource
- Waits for migration to complete
- Optionally verifies network interfaces and SSH
- Returns the migration resource for further assertions

## Migration with Connectivity Verification (Network)

Network migration tests add connectivity checks to prove that VM networking survives live migration.

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

### Bridge Must Exist on Both Nodes

```mermaid
flowchart LR
    Worker1[Worker-1<br>bridge-migration] --> NAD[NAD<br>references bridge]
    Worker2[Worker-2<br>bridge-migration] --> NAD
    NAD --> VM[VM migrates<br>between workers]
```

The bridge NNCP must target all worker nodes (not just one), otherwise migration fails because the destination node has no matching bridge.

### Key Network Utilities

- `migrate_vm_and_verify(vm)` — triggers migration and waits for completion
- `assert_ping_successful(src_vm, dst_ip)` — verifies connectivity post-migration
- `ContinuousPing` — measures downtime during migration

## Migration Variants

| Variant | Test location |
|---|---|
| **Post-copy migration** | `tests/virt/node/migration_and_maintenance/test_post_copy_migration.py` |
| **Storage migration** | `tests/storage/storage_migration/` |
| **Cross-cluster live migration** | `tests/storage/cross_cluster_live_migration/` |
| **Migration during disk/memory load** | `tests/virt/node/migration_and_maintenance/` |
| **Network migration stuntime** | `tests/network/*/migration_stuntime/` |
| **Localnet migration** | `tests/network/localnet/migration_stuntime/` |
