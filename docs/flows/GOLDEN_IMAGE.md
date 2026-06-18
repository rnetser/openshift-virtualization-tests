# Golden Image Pattern

> **Repo-wide pattern.** Used across all test domains:
> `tests/virt/`, `tests/storage/`, `tests/network/`, `tests/infrastructure/`, `tests/install_upgrade_operators/`

The golden image pattern is the foundational approach for VM creation in this repository. It avoids downloading a full OS image for every test. One image is downloaded once per session, then cloned rapidly for each test.

```mermaid
flowchart TD
    A[Session Start] --> B[Download OS image once]
    B --> C[Create golden DataVolume]
    C --> D[Create DataSource pointing to DV]

    D --> E1[Test 1: Clone DV]
    D --> E2[Test 2: Clone DV]
    D --> E3[Test N: Clone DV]

    E1 --> F1[Create VM from clone]
    E2 --> F2[Create VM from clone]
    E3 --> F3[Create VM from clone]

    F1 --> G1[Run test, destroy VM]
    F2 --> G2[Run test, destroy VM]
    F3 --> G3[Run test, destroy VM]
```

## Resource Lifecycle

```mermaid
flowchart TD
    GI_NS[golden_images_namespace<br>session scope] --> GI_DV_M[golden_image_data_volume_scope_module<br>module scope]
    GI_NS --> GI_DV_F[golden_image_data_volume_scope_function<br>function scope]
    GI_DV_F --> GI_DS_F[golden_image_data_source_scope_function<br>function scope]
    GI_DS_F --> Clone[DataVolume clone<br>function scope]
    Clone --> VM[VM boots from clone<br>function scope]
```

## Fixture Chain

1. **`golden_images_namespace`** (session scope) — creates a dedicated namespace for golden images, shared across the entire test session.
2. **`golden_image_data_volume_scope_module`** or **`golden_image_data_volume_scope_function`** — creates a DataVolume from a golden image (selected by OS template + storage class).
3. **`golden_image_data_source_scope_function`** — creates a DataSource pointing to the DataVolume.
4. **Tests** use the DataSource to create VMs via `VirtualMachineForTestsFromTemplate`, which clones the DataVolume and boots a VM from it.

## Why This Matters

- **Without golden image**: Each test downloads a full OS image
- **With golden image**: One download, then fast clones — orders of magnitude faster
- Clone uses CSI volume cloning (copy-on-write when storage supports it)
