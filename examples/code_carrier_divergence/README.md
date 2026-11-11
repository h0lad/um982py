# Code-carrier divergence

Track code-carrier divergence with a filter that resets after cycle slips.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.code_carrier_divergence --port /dev/ttyUSB0 --baud 921600 \
    --duration 300 --tau 100 --threshold 0.05 --record captures/divergence.bin \
    --json divergence.json
```

Replay the supplied capture:

```bash
python -m examples.code_carrier_divergence \
    --replay tests/fixtures/specialist/rtklib-motion.bin \
    --json /tmp/divergence.json
```

## Inputs and results

`--tau` sets the divergence filter time constant in seconds, and `--threshold`
sets the rate threshold in metres per second. `--truth-code` accepts an
independently known constant pseudorange in metres for comparison.

The filter also resets after other breaks in signal continuity. An alert does
not identify a unique physical cause.

## References

Sanz Subirana et al. (2012), GNSS Data Processing.
