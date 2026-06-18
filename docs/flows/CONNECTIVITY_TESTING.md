# Connectivity Testing Patterns

All network tests ultimately verify connectivity between VMs. Several patterns exist depending on what's being tested.

## Ping (Point-in-Time)

```mermaid
flowchart LR
    VM_A[VM-A] -->|ping dst_ip| VM_B[VM-B]
    Result{Packet loss?}
    VM_B --> Result
    Result -->|0%| Pass[✅ Connected]
    Result -->|100%| Fail[❌ Not connected]
```

**Utilities:**
- `utilities.network.assert_ping_successful(src_vm, dst_ip)` — assert ping works
- `utilities.network.ping(src_vm, dst_ip, count)` — returns packet loss count

## TCP (iperf3)

```mermaid
flowchart LR
    Server[VM-B<br>TcpServer on port 5201] --> |listens| Port[TCP :5201]
    Client[VM-A<br>VMTcpClient] --> |connects| Port
    Result{Connection OK?}
    Port --> Result
```

**Utilities:**
- `libs.net.traffic_generator.TcpServer` — starts iperf3 server
- `libs.net.traffic_generator.VMTcpClient` — connects from client VM
- `poll_tcp_connectivity(client_vm, server_vm, server_ip)` — polls until expected state

## Continuous Ping (Migration Stuntime)

```mermaid
flowchart TD
    A[Start ContinuousPing from VM-A to VM-B] --> B[Trigger VM migration]
    B --> C[Migration completes]
    C --> D[Stop ContinuousPing]
    D --> E[Measure packet loss / downtime]
    E --> F{Downtime acceptable?}
    F -->|Yes| G[✅ Pass]
    F -->|No| H[❌ Fail]
```

Used to measure network downtime during live migration. The `ContinuousPing` runs in background, migration happens, then results are checked.

## Negative Testing

Some tests verify that connectivity does NOT exist (network isolation, policy enforcement):

```python
poll_tcp_connectivity(client_vm, server_vm, server_ip, expect_connectivity=False)
```
