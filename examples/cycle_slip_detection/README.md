# Cycle slip detection

Flags cycle slips from Doppler consistency.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

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

`--threshold` controls the Doppler-consistency test, while `--frames` and
`--interval` control the sampled RANGE epochs. Results depend on a continuous
observation arc and the selected threshold.

## Understanding the result

A cycle slip breaks carrier-phase continuity and can introduce a jump that
affects precise positioning. The example compares phase changes with
Doppler-derived expectations. Thresholds, sampling gaps and signal quality
affect the result, so investigate a flag before treating it as a confirmed slip.

## References

Blewitt (1990), GPS cycle-slip editing.
