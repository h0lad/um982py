# Status website

Add these options to the [caster command](README.md#run):

```bash
  --status-port 8080 --status-bind 127.0.0.1 \
  --status-caster-url https://caster.example.org:2101 \
  --status-contact-url https://example.org/request-access
```

Open `http://127.0.0.1:8080/` locally. The contact URL is optional. Set the
caster URL to the caster origin, including its port. Use HTTPS for a non-loopback
hostname or HTTP for a loopback-only caster.

For direct public access, set a numeric non-loopback `--status-bind`. This
requires and reuses the caster's TLS certificate and key. Loopback uses HTTP for
a local reverse proxy, so keep that port private.

`--status-port` publishes telemetry without a login, even when NTRIP requires
an account. In `--mode private`, the status site can bind only to loopback.
Protect any reverse proxy that exposes it.

The page shows rounded station coordinates, frame and epoch,
connection instructions, RTCM receipt ages and mask counts. It also shows
payload rates, aggregate connections, counters and up to 15 minutes of sampled
availability.

Counters reset on restart. Unobserved intervals remain unknown. Receipt age
measures time since the caster received a message. It does not measure GNSS
epoch latency. The page omits C/N₀, DOP, rover fix and accuracy, as well as
accounts, client addresses, rover positions and local paths.

The JSON at `/status.json` is cached once per second. GET/HEAD and ETags are
supported on fixed routes. `/healthz` returns 200 when corrections are ready,
otherwise 503. The browser refreshes every 10–12 seconds and marks reports
unconfirmed after a failed refresh or 15 seconds without fresh data.

For public traffic, use [`nginx-status.conf`](nginx-status.conf) as an
`http`-context include. Set the hostname, certificates, writable cache directory
and backend address, then run `nginx -t` before reloading. Keep the origin
private. Preserve cache TTLs and disable stale serving so an outage cannot
appear healthy. This proxy serves status only and does not proxy NTRIP streams.

The website defaults to 64 connections, eight per IP and 50 accepts/s. Pending
TLS handshakes count toward the admission limit. Adjust `--status-max-clients`
and `--status-per-ip` as needed. Headers must fit within 2048 bytes and arrive
within 3 s. Writes have a 2 s deadline.

The website has its own connection limits but shares CPU, process and network
resources with NTRIP. Use upstream connection limits and external monitoring.
