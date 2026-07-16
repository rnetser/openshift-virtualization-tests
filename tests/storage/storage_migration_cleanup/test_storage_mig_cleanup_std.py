"""Storage migration cleanup STD (partial — linked-repo smoke test).

STP: https://github.com/RedHatQE/openshift-virtualization-tests-design-docs/blob/main/stps/sig-storage/storage_mig_cleanup.md

Preconditions:
    - Cluster with CDI, HCO, and migration controller installed
    - ODF (ocs-storagecluster-ceph-rbd-virtualization) and HPP (hostpath-csi-basic) storage classes available
"""

import pytest

__test__ = False


class TestStorageMigrationCleanupPolicy:
    """
    STD for storage migration source volume cleanup policies.

    Preconditions:
        - Two storage classes available (ODF and HPP)
        - VirtualMachine with disk on source storage class
    """

    @pytest.mark.polarion("CNV-77501")
    def test_source_volumes_cleanup_per_plan_and_namespace_policies(self):
        """
        Verify source volumes are retained or cleaned up correctly per plan-level
        and namespace-level cleanup policies.

        Preconditions:
            - VirtualMachine with disk on source storage class
            - Migration plan targeting a different storage class

        Steps:
            1. Configure cleanup policy at migration plan level to delete source volumes
            2. Execute storage migration for the VM
            3. Wait for migration to complete successfully
            4. Inspect source volumes state
            5. Repeat with namespace-level cleanup policy
            6. Repeat with both plan-level and namespace-level policies to verify override behavior

        Expected:
            Source volumes are deleted or retained according to the configured cleanup policy,
            with namespace-level policy overriding plan-level policy when both are configured
        """
