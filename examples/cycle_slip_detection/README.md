# Cycle slip detection

Check for cycle slips by comparing phase changes with Doppler.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.cycle_slip_detection --port /dev/ttyUSB0 --baud 921600 \
    --json out.json
```

Replay the supplied capture:

```bash
python -m examples.cycle_slip_detection \
    --replay tests/fixtures/captures/RANGEB.bin
```

## Inputs and results

`--threshold` controls the Doppler-consistency test. `--frames` and `--interval`
control the sampled RANGE epochs.

A flag alone does not confirm a slip.

## References

Blewitt (1990), GPS cycle-slip editing.
