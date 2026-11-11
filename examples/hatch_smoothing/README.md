# Hatch smoothing

Smooth code range with carrier-phase changes.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.hatch_smoothing --port /dev/ttyUSB0 --baud 921600 \
    --duration 120 --window 100 --record captures/hatch.bin --json hatch.json
```

Replay the supplied capture:

```bash
python -m examples.hatch_smoothing \
    --replay tests/fixtures/specialist/rtklib-motion.bin \
    --json /tmp/hatch.json
```

## Inputs and results

`--window` sets the smoothing window. Replay needs RANGE observations with
continuous carrier-phase arcs.

## Understanding the result

The filter resets when a cycle slip or gap breaks an arc.

## References

Hatch (1982), code-carrier smoothing.
