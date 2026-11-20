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

The report summarizes notice counters and slot values across the capture.
The slot write mask determines which values enter the statistics. Fields
with unverified meanings remain in their raw form.

## Extract tracking records from baseband containers

If you have a capture of baseband FIFO containers, replay it with:

```bash
python -m examples.baseband_epoch_audit --replay fifo.bin --container-input \
    --json fifo-tracking.json
```

The report validates container checksums and decodes inner message 24 into
the same fields as `PTOBSINFO`. Each tracking record includes the container
sequence, native measurement tag and slot-write mask. The native tag is
preserved as received. A set bit records that a channel wrote the slot.

Python callers can pass an inner frame from `RawBasebandPacket.messages` to
`um982py.experimental.decode_tracking_message`, then use `tracking_slots`
with the resulting record. For live UART acquisition, use the
`PTOBSINFOB` tracking stream in the first example.

## References

Unicore N4 R1.4 interface guide.
