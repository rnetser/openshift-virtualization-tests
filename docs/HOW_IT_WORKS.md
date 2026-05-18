# How This Repo Works

A picture book for understanding openshift-virtualization-tests.

## The Big Picture

```mermaid
flowchart TD
    A[You run 'pytest'] --> B[Reads pytest.ini for rules]
    B --> C[Loads conftest.py files]
    C --> D[Finds tests in tests/ folder]
    D --> E[Makes fixtures like VMs]
    E --> F[Runs the tests]
    F --> G[Shows test results]
```

You ask the computer to run tests. It reads the rules, finds the tests, builds the things needed, and runs them to see if they pass.

## Where Things Live

```mermaid
graph TD
    Root[openshift-virtualization-tests/] --> C1[conftest.py]
    Root --> P[pytest.ini]
    Root --> Tests[tests/]
    Root --> Utils[utilities/]
    Root --> Libs[libs/]

    Tests --> TC[conftest.py]
    Tests --> GC[global_config.py]
    Tests --> TVirt[virt/]
    Tests --> TNet[network/]
    Tests --> TStore[storage/]
    Tests --> TObs[observability/]
    Tests --> TInst[install_upgrade_operators/]
    Tests --> TInfra[infrastructure/]
    Tests --> TChaos[chaos/]

    Utils --> UVirt[virt.py]
    Utils --> UStore[storage.py]
    Utils --> UInfra[infra.py]
    Utils --> UClust[cluster.py]
    Utils --> UConst[constants.py]
    Utils --> UArch[architecture.py]

    Libs --> LVm[vm/]
    Libs --> LNet[net/]
    Libs --> LStore[storage/]
```

Think of the repository like a house with different rooms. `tests/` is where the tests play, `utilities/` is the toolbox for fixing things, and `libs/` has the blocks to build stuff.

## What is a Fixture?

```mermaid
flowchart LR
    Test[Your Test] -- "I need a VM!" --> Fixture[Fixture Helper]
    Fixture -- "Here is a VM" --> Test
    Test -- "I'm done running" --> Fixture
    Fixture -- "Cleaning up VM" --> Trash[Trash]
```

A fixture is a magical helper that makes things for your test and cleans them up after. If your test needs a Virtual Machine (VM) or a namespace, you just ask the fixture, and it gives you one!

```python
def test_my_thing(running_vm):  # ← 'give me a running VM'
    assert running_vm.status == 'Running'  # use it
# pytest handles creation AND cleanup
```

## The Conftest Chain

```mermaid
flowchart TD
    Root[conftest.py: plugins, CLI args] --> Tests[tests/conftest.py: session fixtures, VMs, images]
    Tests --> Net[tests/network/conftest.py: network bridges, NADs]
    Net --> SRIOV[tests/network/sriov/conftest.py: SR-IOV fixtures]
```

Conftest files are like rulebooks that share fixtures. Big rulebooks at the top share with everyone, and small rulebooks at the bottom only share with specific tests. Inner tests can use fixtures from any rulebook above them.

## Fixture Lifecycle (Scope)

```mermaid
flowchart TD
    subgraph SESSION [SESSION - Entire test run]
    A[Admin Client, Namespaces, Golden Images]
    end

    subgraph MODULE [MODULE - One test file]
    B[Data Volumes]
    end

    subgraph CLASS [CLASS - One test class]
    C[Class VMs]
    end

    subgraph FUNCTION [FUNCTION - One test]
    D[Function VMs]
    end

    SESSION --> MODULE --> CLASS --> FUNCTION
```

Some fixtures take a long time to build, so we keep them alive for the whole test run (Session). Others are quick, so we make them fresh for every single test (Function) and throw them away right after.

## The Golden Image Pattern

```mermaid
flowchart TD
    1[SESSION: Download big OS image once] --> 2[Make golden DataVolume: ~5 min]
    2 --> 3[Make DataSource pointing to it]
    3 --> 4[MODULE/CLASS: Clone it fast: ~10 sec]
    4 --> 5[FUNCTION: Make a VM from the clone]
    5 --> 6[Run test and trash VM]
    6 --> 4[Make next clone]
```

The golden image is like a master photocopy. Instead of downloading an image from scratch for every test, we download it once and make very fast copies (clones) for each test.

## How Architecture Detection Works

```mermaid
flowchart TD
    A{Is OPENSHIFT_VIRTUALIZATION_TEST_IMAGES_ARCH set?} -- YES --> B[Use CI mode architecture]
    A -- NO --> C{Is pytest running with --help?}
    C -- YES --> D[Return amd64 and skip cluster]
    C -- NO --> E[Connect to cluster]
    E --> F[Read node labels]
    F --> G[Return architecture set]

    B --> H
    D --> H
    G --> H[Pick correct Images class: AMD64, ARM64, S390X]
```

The tests need to know what kind of computer brains (CPU architecture) the cluster uses. It checks settings or looks at the cluster to pick the right container images.

## The Marker System

```mermaid
flowchart LR
    Test[A Single Test] --> M1(tier1: infra tests)
    Test --> M2(tier2: default user cases)
    Test --> M3(tier3: slow/hardware)
    Test --> M4(gating: must pass)
    Test --> M5(network/storage/virt: auto teams)
    Test --> M6(sriov/gpu: hardware)
```

Markers are like tags you put on tests so you can find them later. You can say "Run only the Network tests" or "Run only the quick Tier 1 tests" using these tags.

## Configuration Flow

```mermaid
flowchart TD
    A[pytest.ini] --> B[markers, test paths]
    C[tests/global_config.py] --> D[Builds py_config dictionary]
    E[Environment Variables] --> D
    F[CLI arguments] --> D

    D --> G[Fixtures use this to configure VMs and Storage]
```

The config flow gathers settings from files, commands, and the environment. It puts them all into one big dictionary so the fixtures know exactly how to build things.

## How Storage Works

```mermaid
flowchart TD
    A[Cluster has StorageClasses: Ceph, NFS, HostPath] --> B[Matrix Fixtures read classes]
    B --> C[pytest_generate_tests hook]
    C --> D[Run test with Ceph]
    C --> E[Run test with NFS]
    C --> F[Run test with HostPath]
```

Different clusters save files in different ways using StorageClasses. The tests automatically find what is available and run the same test on every type of storage to make sure they all work.

## Test Domains at a Glance

```mermaid
flowchart TD
    A[VIRT] --> |Lifecycle, Migration, Hotplug| B(VMs)
    C[NETWORK] --> |Bridges, SR-IOV, IPv6| D(Cables)
    E[STORAGE] --> |Snapshots, Clones, Uploads| F(Disks)
    G[OBSERVABILITY] --> |Metrics, Alerts| H(Graphs)
    I[INSTALL_UPGRADE] --> |Operators, HCO| J(Setup)
    K[INFRASTRUCTURE] --> |Console, Machine Types| L(Core)
    M[CHAOS] --> |Disruption, Backup| N(Breaking)
```

The tests are split into different neighborhoods based on what they do. Virt tests play with virtual machines, Network tests play with cables, and Chaos tests just like breaking things.

## Key Utilities Quick Reference

| File | What it does | Example functions |
|------|-------------|------------------|
| utilities/virt.py | VM operations | VirtualMachineForTests, migrate_vm, wait_for_vm_interfaces |
| utilities/storage.py | Storage operations | data_volume(), create_or_update_data_source() |
| utilities/infra.py | Infrastructure | create_ns(), ExecCommandOnPod, run_command |
| utilities/cluster.py | Cluster ops | cache_admin_client(), get_nodes_by_type |
| utilities/constants.py | All constants | Images, StorageClassNames, timeouts |
| utilities/monitoring.py | Prometheus | get_metric_value(), wait_for_alert |
| utilities/network.py | Network helpers | network operations |
| libs/vm/vm.py | VM builder | VirtualMachineForTests class |
| libs/vm/factory.py | VM factory | create VM specs programmatically |

Helper files are neatly organized so you can quickly find the tools you need. Just grab the right file for the job!
