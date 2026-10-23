# Hatch smoothing

Smooths code with carrier phase and resets on cycle slips.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

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
continuous carrier-phase arcs, and the filter resets when its cycle-slip checks
break an arc.

## Understanding the result

A Hatch filter uses carrier-phase changes to smooth noisier code-range
measurements over continuous signal arcs. The filter resets when a cycle slip or
gap breaks an arc, and smoothing does not remove every source of measurement
bias.

## References

Hatch (1982), code-carrier smoothing.
