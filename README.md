# openshift-virtualization-tests

This repository contains tests to verify the functionality of OpenShift with
[OpenShift Virtualization](https://www.redhat.com/en/technologies/cloud-computing/openshift/virtualization), formerly named `CNV` (Container Native Virtualization)

The tests are written in Python and use [pytest](https://docs.pytest.org/en/stable/) as a test framework.


## Getting started and running the tests
Please follow the [Getting Started Guide](docs/GETTING_STARTED.md) and [Run the tests](docs/RUNNING_TESTS.md) on how to run the tests.

## Contribute to openshift-virtualization-tests
Please follow the [Contributing Guide](docs/CONTRIBUTING.md) and the [Developer guide](docs/DEVELOPER_GUIDE.md)


## Build and push
Please follow the [Build and Push Guide](docs/CONTAINERIZE_TESTS.md) on how to build and push the tests.

## Install and Upgrade tests
Follow the [Install and Upgrade Guide](docs/INSTALL_AND_UPGRADE.md) on how to run the tests.


## Run basic tests on standard cluster
To run tests on a standard cluster configuration (more than 1 node is required), use the following command:

```bash
uv run pytest -m "conformance" --default-storage-class <cluster default storage class> --skip-artifactory-check
```

To run on single-node cluster, use the following command:
```bash
uv run pytest -m "conformance and sno" --default-storage-class <cluster default storage class> --skip-artifactory-check
```

To run on single-nic cluster, use the following command:
```bash
uv run pytest -m "conformance and single_nic" --default-storage-class <cluster default storage class> --skip-artifactory-check
```

To run on an SR-IOV cluster, use the following command:
```bash
uv run pytest -m "conformance and sriov" --default-storage-class <cluster default storage class> --skip-artifactory-check
```

The default storage classes that are covered include: `ocs-storagecluster-ceph-rbd-virtualization`, `hostpath-csi-basic` and `hostpath-csi-pvc-block`
To modify the set of storage classes that are tested:
- Make a copy of [global_config.py](tests/global_config.py) file
- Edit `storage_class_matrix` variable to match the storage classes you want to test
- Run the tests using the new global_config.py file, example:
```bash
uv run pytest -m "conformance" --default-storage-class <cluster default storage class> --skip-artifactory-check --tc-file=tests/global_config_new.py
```
