# Time to first fix

Measure time to first fix after cold or warm starts.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.ttff_profile --port /dev/ttyUSB0 --baud 921600 --start cold \
    --runs 3 --json out.json
```

Replay the supplied capture:

```bash
python -m examples.ttff_profile \
    --replay tests/fixtures/captures-live/BESTPOSA.bin --start warm \
    --json out.json
```

## Inputs and results

`--start` selects cold or warm starts, and `--runs` sets the number of live
trials. Live trials issue receiver reset commands. Replay evaluates the
captured epochs and does not perform a new start.

## References

Unicore UM982 user manual, reset and startup.
