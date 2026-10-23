# Status website

Add these options to the [caster command](README.md#run):

```bash
  --status-port 8080 --status-bind 127.0.0.1 \
  --status-caster-url https://caster.example.org:2101 \
  --status-contact-url https://example.org/request-access
```

Open `http://127.0.0.1:8080/` locally. The contact URL is optional. The caster
URL must be the caster origin, including port. Use HTTPS for a non-loopback
hostname, or HTTP for a loopback-only caster. For direct public access,
set a numeric non-loopback `--status-bind`, which requires and reuses the
caster's TLS certificate and key. Loopback uses HTTP for a local reverse proxy, so
keep that port private. In `--mode private`, the application only permits the
status site to bind to loopback, because the site itself has no login. Protect
any reverse proxy that exposes it.

`--status-port` publishes telemetry even when the NTRIP stream requires an
account. It exposes rounded station coordinates, frame/epoch, connection
instructions, RTCM receipt ages and mask counts, payload rates, aggregate
connections, counters and up to 15 minutes of sampled availability. Counters
reset on restart, and unobserved time remains unknown. Receipt age measures
when the caster received a message, not GNSS epoch latency. The status does not
include C/N₀, DOP, rover fix or accuracy, and omits accounts, client addresses,
rover positions and local paths.

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
TLS handshakes count toward the admission limit. Adjust `--status-max-clients` and
`--status-per-ip` as needed. Headers are limited to 2048 bytes / 3 s, writes to
2 s. Its connection budget is separate from NTRIP, but CPU, process and network
remain shared. Use upstream connection limits and external monitoring.
