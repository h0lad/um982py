# Tracking field lab

Correlate tracking fields of unknown meaning with your own labels.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.tracking_field_lab --port /dev/ttyUSB0 --baud 921600 \
    --duration 60 --record captures/tracking.bin --json tracking.json
```

Replay the supplied capture:

```bash
python -m examples.tracking_field_lab \
    --replay tests/fixtures/specialist/labelled-tracking.bin \
    --labels tests/fixtures/specialist/tracking-labels.csv \
    --json /tmp/field-hypotheses.json
```

## Inputs and results

`--labels` accepts an independent CSV with `epoch,value` columns. The epoch is
absolute GPS time in seconds. `--join-tolerance` limits the time difference,
and the selector options filter repeated epochs by a neutral field.

The report includes the written slot indices for each selected frame. It
excludes fields whose write-mask bits are clear, even if a selector targets an
unwritten slot. A written slot may still contain an invalid or overwritten
value. The section below gives the verified meaning of the float slots.

## What the slots measure

The eighteen float slots of `PTOBSINFO` are two banks of nine, ANT1 then ANT2.
Each written slot equalled, within 0.01 dB, the mean C/N0
of the three or four strongest satellites of one RF group in `RANGE` (ANT1) or
`RANGEH` (ANT2) at the same epoch: GPS L1 C/A, GPS L2C, GLONASS G1 and G2,
BeiDou B1I and B3I, Galileo E5b and E5a, in bank-slot order. The Galileo E1
slot did not match better than 0.16 dB, and the number of averaged satellites
varied between the two captures checked.
`TrackingSlot.reference_cn0_db_hz`, `antenna` and `rf_group` expose this
reading. A drop across one group of one antenna indicates interference rather
than a single-satellite fade. The integer fields before the slots remain
unverified.

## References

Unicore N4 R1.4 interface guide.
