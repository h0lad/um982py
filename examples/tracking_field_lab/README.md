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
value. Its physical unit and signal identity remain unknown.

## References

Unicore N4 R1.4 interface guide.
