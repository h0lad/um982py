# Field validation before unattended use

This is a repeatable acceptance procedure, not a completed certification or an
accuracy claim. Run it on each deployed receiver/firmware/transport combination.
Do not inject faults into a receiver currently used to navigate or survey.

## 1. Record the setup and acceptance limits

Save the git commit, Python/OS versions, receiver model/serial/firmware, antenna
models and offsets, power source, connection type, UART baud rate, log names and
rates, correction service, and approximate sky conditions. Redact credentials
and sensitive locations before publishing artifacts.

Before testing, choose limits for measurement gap, recovery time, position age,
correction age, memory growth, and allowed queue drops. Set these from the actual
application; an RTK survey and vehicle tracking do not have the same limits.
Record the receiver configuration before changing it. Save/reboot operations
must be deliberate; retain a known-good way to restore the configuration.

## 2. Run the hardware smoke suite

From a development installation, with a dedicated test receiver:

```bash
python -m pytest tests/hardware --hardware-port /dev/ttyUSB0 \
  --hardware-baud 921600 --soak-seconds 60 \
  --hardware-report hardware-report.json
```

Read the hardware tests before running them: they exercise receiver commands
and subscriptions. A smoke-suite pass does not substitute for the soak below.
Use the actual port and baud rate, not necessarily these example values.

## 3. Soak the application, not just the decoder

Run the intended application for at least 24 hours at its intended output rates,
then repeat at the highest supported rate you intend to deploy. Use the same
serial/TCP gateway, correction source, recording disk, and consumer workload.
Keep raw segmented recordings with `SessionRecorder`; retain gap events and
segment checksums. Do not use an unbounded in-memory capture for the soak.

Sample health at least once per second and preserve a timestamped event log:

- `StreamHealth`: message count, subscription drops, discarded bytes, recent
  decoder errors, failure, last arrival, and receiver time;
- each subscription's `dropped` counter and configured capacity;
- `RtkHealth`: state, connection attempts, reconnects, frames forwarded, last
  byte/correction times, and last error;
- `RoverSessionHealth`: connections, positions, state, and last error;
- receiver solution class, measurement epoch/time status, correction age and
  precision when present; process RSS, CPU, recording size and free disk space.

Recent decoder errors are a bounded history, not a cumulative error counter.
Host completion/dispatch times measure transport/application behavior, not
measurement age. Report receiver epoch gaps separately from host arrival gaps.
Forwarding age is not receiver-reported correction age or end-to-end latency.
Missing time or quality fields must remain unknown, not count as good.

## 4. Inject faults and record recovery

Repeat each fault at least three times; timestamp injection and recovery. State
whether recovery is automatic or requires reopening the session/application.

| Fault | Required observation |
| --- | --- |
| Unplug/reconnect serial or interrupt TCP | No hang; error/outage visible; configured reconnect policy honored |
| Power-cycle receiver | No previous-session carrier arc or stale fix silently reused |
| Disable corrections for 60 seconds | Loss/age visible; forwarded bytes not mistaken for applied corrections |
| Stall a subscriber until its queue fills | Drops visible; other consumers remain responsive; recovery bounded |
| Interrupt recording / simulate a full test volume | Failure surfaced; partial segments and gaps identifiable |
| Cancel/close while I/O is pending | Shutdown bounded by configured I/O policy; receiver ownership released |

Use a disposable volume to test disk exhaustion, not the workstation's root
filesystem. For every interruption, verify epoch continuity or an explicit gap
and a new source session where appropriate. Check effective configuration after
recovery; never assume that a reboot or close restored prior settings.

## 5. Verify artifacts independently

Replay completed segments, verify checksums, and compare message/epoch counts
against live telemetry. Export observations with station/antenna metadata and a
fixed timezone-aware `created_at`; compare exports across repeated replay.
Use RTKLIB and independent parsers/reference products where available. Run:

```bash
python -m pytest tests/test_external_references.py tests/test_rinex_rtklib.py
```

Report every skip and configure the external tools/datasets described in those
tests. Survey accuracy needs a surveyed reference, reference frame/epoch,
antenna calibration, and an explicit uncertainty budget. Receiver standard
deviations alone do not demonstrate accuracy or integrity.

## Report template

- Setup and artifact locations (including raw captures and configuration)
- Application-selected limits and why they were chosen
- Duration, rates requested and rates measured, CPU/RSS trends
- Drops, discarded bytes, epoch gaps, missing/invalid time or quality
- Per-fault attempts, errors, recovery times and configuration changes
- Correction outages and receiver-reported age/solution transitions
- Replay/export/reference comparison results, skips and unresolved failures
- Pass/fail **against the chosen limits**, with untested cases listed

A passing report supports only the tested configuration and workload. It does
not establish flight certification, maritime integrity, absolute accuracy, or
performance for other firmware, antennas, gateways, or output rates.
