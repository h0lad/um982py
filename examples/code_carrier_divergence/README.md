# Code-carrier divergence

Tracks code-carrier divergence and resets after cycle slips.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

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

## Understanding the result

GNSS receivers measure both a code-based range and a carrier-phase quantity.
This example tracks how those measurements diverge over a continuous signal
arc and flags rates exceeding a chosen threshold.

A cycle slip is a loss or change in carrier-phase continuity, and the filter
resets when an arc breaks. A divergence alert does not identify a unique
physical cause.

## References

Sanz Subirana et al. (2012), GNSS Data Processing.
