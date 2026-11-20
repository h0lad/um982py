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

## Export native BINEX observations

`um982py.binex.binex_output()` subscribes to `BINEX7F05`. The stream decoder
reads these frames alongside standard receiver logs. Use `binex_epoch()` to
inspect the time tag, satellite count and clock fields, and
`binex_satellites()` to inspect the encoded satellite blocks.

Export a mixed recording to a standalone BINEX file:

```python
from pathlib import Path

from um982py.binex import write_binex
from um982py.capture import iter_frames

with Path("observations.bnx").open("xb") as output:
    epochs = write_binex(iter_frames(Path("wire.bin")), output, drop_zero_prn=True)
print(f"Exported {epochs} BINEX epochs")
```

By default `write_binex` copies original frames. With `drop_zero_prn=True`,
it removes satellite-number-zero blocks, updates the satellite count and
recomputes the checksum. RTKLIB converted all 20 epochs from a UM982 capture
after this cleanup. The 200 GPS L1 C/A pseudoranges matched simultaneous
`RANGE` to within 0.5 mm. The decoder supports big-endian forward
`0x7f-05` records with an XOR checksum or CRC-16.
[BINEX 0x7f-05 field layout](https://www.unavco.org/data/gps-gnss/data-formats/binex/binex_record_7f.html)

## References

Unicore N4 R1.4 interface guide.
