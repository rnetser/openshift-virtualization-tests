"""Scratch space storage class selection STD (partial — 1 of 4 P0 scenarios).

STP: https://github.com/RedHatQE/openshift-virtualization-tests-design-docs/blob/main/stps/sig-storage/scratch_space_sc_selection_logic.md

Preconditions:
    - Cluster with CDI and HCO installed
    - At least two storage classes available
"""

import pytest

__test__ = False


class TestScratchSpaceImportConversion:
    """
    STD for scratch space allocation during import with conversion.

    Preconditions:
        - Source image requires format conversion
        - Target DataVolume storage class is configured
    """

    @pytest.mark.polarion("CNV-72238")
    def test_import_conversion_uses_target_dv_storage_class(self):
        """
        Verify import requiring conversion allocates scratch space using target DataVolume storage class.

        Preconditions:
            - HTTP DataSource or registry import source available

        Steps:
            1. Create a DataVolume import that requires conversion
            2. Inspect the scratch space PVC created during import

        Expected:
            Scratch space PVC uses the same storage class as the target DataVolume
        """
