from dataclasses import dataclass

from ocp_resources.datavolume import DataVolume

from utilities.constants import HPP_CAPABILITIES, StorageClassNames
from utilities.storage import HppCsiStorageClass


@dataclass
class StorageClass:
    name: str
    volume_mode: str
    access_mode: str
    snapshot: bool
    online_resize: bool
    wffc: bool
    default: bool = False


supported_storage_classes = [
    StorageClass(
        name=StorageClassNames.CEPH_RBD_VIRTUALIZATION,
        volume_mode=DataVolume.VolumeMode.BLOCK,
        access_mode=DataVolume.AccessMode.RWX,
        snapshot=True,
        online_resize=True,
        wffc=False,
        default=True,
    ),
    StorageClass(name=HppCsiStorageClass.Name.HOSTPATH_CSI_BASIC, **HPP_CAPABILITIES),
    StorageClass(name=HppCsiStorageClass.Name.HOSTPATH_CSI_PVC_BLOCK, **HPP_CAPABILITIES),
]
