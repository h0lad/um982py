# Baseband epoch audit

Audits diagnostic counters and PTOBSINFO tracking slots.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

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

`--enable-gate` enables BBMSG2AP for the capture and disables it afterward. Its
previous state cannot be queried, so the example cannot restore an earlier
enabled state. The report audits native counters and tracking slots without
assigning unverified meanings.

## Understanding the result

An epoch is a receiver measurement time. This diagnostic groups available
baseband counters and PTOBSINFO tracking-slot records around those epochs to
help inspect their behaviour.

The report preserves fields whose meaning is not verified rather than treating
them as established measurements. The optional live gate changes receiver
state as described below.

## References

Unicore N4 R1.4 interface guide.
