# Triple-frequency closure

Tests triple-frequency combinations that cancel geometry and ionosphere.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

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

The selected three-frequency combination cancels common effects under the
chosen model. This experiment examines its phase changes over continuous
tracking arcs.

It requires three suitable signals and enough matching observations. Gaps or
cycle slips break continuity, and a threshold crossing is not automatically
proof of a specific fault.

## References

Sanz Subirana et al. (2013), GNSS Data Processing.
