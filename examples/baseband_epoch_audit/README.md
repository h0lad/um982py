# Baseband epoch audit

Inspect diagnostic counters and PTOBSINFO tracking slots.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.baseband_epoch_audit --port /dev/ttyUSB0 --baud 921600 \
    --duration 15 --enable-gate --record /tmp/bb-audit.bin \
    --json /tmp/bb-audit.json
```

Replay a capture:

```bash
python -m examples.baseband_epoch_audit --replay /tmp/bb-audit.bin \
    --json /tmp/bb-replay.json
```

## Inputs and results

`--enable-gate` enables BBMSG2AP for the capture and disables it afterward, even
if it was already enabled. The previous state cannot be queried.

## Understanding the result

The report groups counters and tracking slots by receiver epoch. Fields with
unverified meanings remain in their raw form.

## References

Unicore N4 R1.4 interface guide.
