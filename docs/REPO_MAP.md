# Repo Map 🗺️

Lost? This page tells you exactly where everything is in our code house. Think of it as a picture book to find what you need! 🎈

## The Map

Here is the big picture of where files and folders live.

```mermaid
graph LR
    Root[🏠 cnv-fork]

    %% Main folders
    Root --> Tests[📁 tests/ <br> All tests live here!]
    Root --> Utils[📁 utilities/ <br> Helper functions]
    Root --> Libs[📁 libs/ <br> Reusable building blocks]
    Root --> Configs[⚙️ Root Configs]

    %% Under Tests
    Tests --> Virt[📁 virt/ <br> VMs, hotplug, templates]
    Tests --> Net[📁 network/ <br> Bridges, SR-IOV, IPv6]
    Tests --> Store[📁 storage/ <br> DataVolumes, snapshots]
    Tests --> Obs[📁 observability/ <br> Metrics & alerts]
    Tests --> IUO[📁 install_upgrade_operators/ <br> Install & upgrade]
    Tests --> Infra[📁 infrastructure/ <br> Console proxy, SSP]
    Tests --> Chaos[📁 chaos/ <br> Disruption tests]
    Tests --> TConf[📄 conftest.py <br> The BIG fixture file]

    %% Root Files
    Configs --> RConf[📄 conftest.py <br> Root pytest config]
    Configs --> PIni[📄 pytest.ini <br> Markers & settings]
    Configs --> PToml[📄 pyproject.toml <br> Dependencies & linters]
    Configs --> Tox[📄 tox.ini <br> CI test commands]
```

---

## I Need To... 👉 Look Here

When you want to do something, just look it up in this magic table!

| I need to... | Look in |
|---|---|
| Find a test for feature X | `tests/<domain>/<feature>/` |
| Find a fixture that creates a VM | `tests/conftest.py` (search for `vm_instance`) |
| Find a fixture that creates storage | `tests/conftest.py` (search for `data_volume`) |
| Find a fixture that creates a namespace | `tests/conftest.py` (search for `namespace`) |
| Find a network-specific fixture | `tests/network/conftest.py` |
| Find a storage-specific fixture | `tests/storage/conftest.py` |
| Find a virt-specific fixture | `tests/virt/conftest.py` |
| Write a VM helper function | `utilities/virt.py` |
| Write a storage helper | `utilities/storage.py` |
| Write a network helper | `utilities/network.py` or `utilities/infra.py` |
| Write a cluster helper | `utilities/cluster.py` |
| Find constants (images, timeouts) | `utilities/constants.py` |
| Find pytest markers | `pytest.ini` |
| Change CI commands | `tox.ini` |
| Change linter rules | `pyproject.toml` and `.flake8` |
| Change container image | `Dockerfile` |
| See coding rules | `AGENTS.md` |
| Check test run instructions | `docs/RUNNING_TESTS.md` |

---

## The Fixture Dependency Tree 🌳

Fixtures are helpers that build things for your test. Many fixtures build on top of other fixtures!

```mermaid
graph TD
    %% Root Client
    Admin["🛠️ admin_client (session)"]

    %% Nodes
    Admin --> Nodes["🖥️ nodes (session)"]
    Nodes --> Sched["🖥️ schedulable_nodes (session)"]
    Nodes --> Workers["🖥️ workers (session)"]

    %% Unprivileged
    Admin --> Unpriv["👤 unprivileged_client (session)"]
    Unpriv --> UnprivSec["🔑 unprivileged_secret"]
    Unpriv --> IDP["🆔 identity_provider_with_htpasswd"]

    %% Golden Images
    Admin --> GI_NS["📁 golden_images_namespace (session)"]
    GI_NS --> GI_DV["💿 golden_image_data_volume_scope_module (module)"]
    GI_DV --> GI_DS["💽 golden_image_data_source_scope_module (module)"]
    GI_NS --> Rhel9["🐧 rhel9_data_source_scope_session (session)"]

    %% Namespaces and VMs
    Admin --> NS["📦 namespace (class)"]
    NS --> DVSF["💾 data_volume_scope_function (function)"]
    NS --> DVMSSF["💾 data_volume_multi_storage_scope_function (function)"]
    DVMSSF --> VMIT["💻 vm_instance_from_template_multi_storage_scope_function (function)"]

    %% Utilities
    Admin --> CNV_NS["🔧 cnv_tests_utilities_namespace (session)"]
    CNV_NS --> UtilDS["⚙️ utility_daemonset (session)"]
    UtilDS --> WUP["🏃 workers_utility_pods (session)"]

    %% HCO
    Admin --> HCO_NS["🏥 hco_namespace (session)"]
    HCO_NS --> CSV["📄 csv_scope_session (session)"]
```

**What do the arrows mean?**
Arrows mean *depends on*. If you ask for the VM at the bottom (`vm_instance_from_template...`), pytest will automatically create the storage (`data_volume...`), the namespace (`namespace`), and the client (`admin_client`) above it!

---

## The conftest.py Chain 🔗

When you run a test, Pytest walks down the folder tree and picks up tools (`conftest.py` files) along the way.

**Example 1: Running a Network Test**
```mermaid
graph TD
    A["1️⃣ conftest.py (root) <br> plugins, CLI args"] --> B["2️⃣ tests/conftest.py <br> admin_client, namespace, VMs, golden images"]
    B --> C["3️⃣ tests/network/conftest.py <br> network sanity, NAD fixtures"]
    C --> D["4️⃣ tests/network/sriov/conftest.py <br> SR-IOV specific fixtures"]
    D --> E((("🚀 Running: tests/network/sriov/test_sriov_basic.py")))
```

**Example 2: Running a Storage Test**
```mermaid
graph TD
    A["1️⃣ conftest.py (root)"] --> B["2️⃣ tests/conftest.py"]
    B --> C["3️⃣ tests/storage/conftest.py <br> storage sanity, storage-specific fixtures"]
    C --> D((("🚀 Running: tests/storage/test_hotplug.py")))
```

💡 **Key insight:** You get ALL fixtures from parent `conftest.py` files automatically!

---

## Files That Matter 🌟

These are the most important files in the whole repo. If you know these, you know everything.

| File | Lines | What it does |
|---|---|---|
| `tests/conftest.py` | ~2800 | The mother of all fixtures. Makes VMs, namespaces, clients. |
| `utilities/constants.py` | ~900 | Every constant, image path, and timeout lives here. |
| `utilities/virt.py` | ~800 | VM helper functions (start, stop, migrate). |
| `utilities/storage.py` | ~600 | Storage helper functions (disks, PVCs). |
| `utilities/infra.py` | ~500 | Infrastructure helpers (nodes, pods, SSH). |
| `tests/global_config.py` | ~200 | Cluster configuration that gets loaded at startup. |
| `pytest.ini` | ~110 | All custom markers (`@pytest.mark...`) are defined here. |
| `conftest.py` (root) | ~800 | Pytest hooks and plugins. Handles test setup logic. |
