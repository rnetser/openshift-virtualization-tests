# NIC Hot-Plug Flow

Hot-plug adds or removes network interfaces to a running VM without reboot.

## Hot-Plug (Add Interface)

```mermaid
flowchart TD
    A[Running VM with primary interface only] --> B[hot_plug_interface]
    B --> C[Update VM spec: add interface + network]
    C --> D[ResourceEditor patches VM]
    D --> E[Wait for interface in VMI status]
    E --> F[Guest agent reports new interface]
    F --> G[set_secondary_static_ip_address]
    G --> H[Console command: ip addr add]
    H --> I[Verify IP via lookup_iface_status_ip]
```

## Hot-Unplug (Remove Interface)

```mermaid
flowchart TD
    A[Running VM with hot-plugged interface] --> B[hot_unplug_interface]
    B --> C[Set interface state to absent in VM spec]
    C --> D[ResourceEditor patches VM]
    D --> E[wait_for_missing_iface_status]
    E --> F[Interface removed from VMI status]
```

## MAC Pool Integration

When KubeMacPool is enabled, hot-plug/unplug triggers MAC allocation/release:

```mermaid
flowchart LR
    HotPlug[Hot-Plug] --> KMP[KubeMacPool allocates MAC]
    HotUnplug[Hot-Unplug] --> KMP2[KubeMacPool releases MAC]
    KMP2 --> Verify[Check controller log for release message]
```
