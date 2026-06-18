# VM Creation Flows

Two approaches exist:

## Modern Factory (`libs/vm/factory`)

Used in: localnet, UDN, l2_bridge (newer), primary_network

```mermaid
flowchart TD
    A[base_vmspec] --> B[Configure spec]
    B --> C1[Set interfaces + networks on spec]
    B --> C2[Set cloud-init disk/volume]
    B --> C3[Set affinity/labels]
    C1 --> D[fedora_vm namespace, name, client, spec]
    C2 --> D
    C3 --> D
    D --> E[BaseVirtualMachine]
    E --> F[vm.start wait=True]
    F --> G[vm.wait_for_agent_connected]
```

Key pattern:
- `base_vmspec()` creates an empty `VMSpec` dataclass
- Modify `spec.template.spec.domain.devices.interfaces` and `spec.template.spec.networks`
- `fedora_vm()` adds container disk, CPU, memory defaults
- Returns `BaseVirtualMachine` (subclass of ocp_resources VirtualMachine)

## Legacy Pattern (`utilities/virt`)

Used in: sriov, migration, bond, macspoof, nmstate, kubemacpool

```mermaid
flowchart TD
    A[fedora_vm_body name] --> B[VirtualMachineForTests]
    B --> C[Pass networks, interfaces, cloud_init_data, macs]
    C --> D[vm.start wait=True]
    D --> E[vm.wait_for_agent_connected]
```

Key pattern:
- `fedora_vm_body(name)` generates a dict-based VM body
- `VirtualMachineForTests` wraps it with networks/interfaces as constructor args
- Interfaces specified as dict keys, interface types via `interfaces_types` param

## Choosing Between Them

- **New tests**: Use the modern factory (`base_vmspec` + `fedora_vm`)
- **Existing tests**: May still use legacy pattern — both work
- The modern factory uses Python dataclasses (`VMSpec`, `Interface`, `Network`) instead of raw dicts
