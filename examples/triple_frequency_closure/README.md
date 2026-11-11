# Triple-frequency closure

Test triple-frequency combinations that cancel geometry and ionosphere.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.triple_frequency_closure --port /dev/ttyUSB0 --baud 921600 \
    --duration 60 --record /tmp/closure.bin --json /tmp/closure.json
```

Replay a capture:

```bash
python -m examples.triple_frequency_closure --replay /tmp/closure.bin \
    --json /tmp/closure-replay.json
```

## Inputs and results

Use `--system` and `--signals` to select the constellation and three signal
IDs. `--threshold` sets the experimental phase-increment threshold in metres.

## Understanding the result

The test needs matching observations over continuous tracking arcs. Gaps or
cycle slips break continuity, and a threshold crossing does not identify a
specific fault.

## References

Sanz Subirana et al. (2013), GNSS Data Processing.
