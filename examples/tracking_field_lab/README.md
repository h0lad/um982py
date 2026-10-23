# Tracking field lab

Correlates unknown tracking fields with your own labels.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

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

`--labels` accepts an independent CSV with `epoch,value` columns, where epoch
is absolute GPS time in seconds. `--join-tolerance` bounds the time match, and
the selector options filter repeated epochs by a neutral field.

The report includes the written slot indices for each selected frame. It
excludes slot fields whose write-mask bits are clear, including when a selector
targets an unwritten slot. A written slot can still contain an invalid or
overwritten value and does not establish a physical unit or signal identity.

## Understanding the result

This research tool compares receiver tracking fields whose meanings are not
yet established with independently supplied labels. It helps identify
candidate relationships in captured data.

A statistical association is a hypothesis, not a verified field definition.
Labels and epochs must align, and results should be checked on independent
captures.

## References

Unicore N4 R1.4 interface guide.
