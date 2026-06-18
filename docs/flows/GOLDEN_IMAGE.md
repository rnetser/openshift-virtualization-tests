# Golden Image Pattern

The golden image pattern avoids downloading a full OS image for every test. One image is downloaded once per session, then cloned rapidly for each test.

```mermaid
flowchart TD
    A[Session Start] --> B[Download OS image once]
    B --> C[Create golden DataVolume ~5 min]
    C --> D[Create DataSource pointing to DV]

    D --> E1[Test 1: Clone DV ~10 sec]
    D --> E2[Test 2: Clone DV ~10 sec]
    D --> E3[Test N: Clone DV ~10 sec]

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

## Why This Matters

- **Without golden image**: Each test downloads ~1GB image → 5+ min per test
- **With golden image**: One download, then ~10 sec clones → orders of magnitude faster
- Clone uses CSI volume cloning (copy-on-write when storage supports it)
