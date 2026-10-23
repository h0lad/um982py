# Dual-antenna spoofing checks

Cross-checks heading, visibility, and spoof indicators.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

Connect to a receiver:

```bash
python -m examples.spoof_dual_antenna --port /dev/ttyUSB0 --baud 921600 \
    --json spoof.json
```

Replay the supplied capture:

```bash
python -m examples.spoof_dual_antenna \
    --replay tests/fixtures/captures/BSLNENUHDA.bin
```

## Inputs and results

The checks use available heading, visibility and spoof indicators. A result
depends on the logs present and should be interpreted as diagnostic evidence.

## Understanding the result

A dual-antenna receiver can report heading and other indicators that help
investigate inconsistent signals. This example cross-checks the available
heading, visibility and spoofing-related receiver fields.

Missing logs, antenna
placement, receiver settings and ordinary interference can affect the result.

## References

Kaplan & Hegarty (2017); Unicore UM982 manual.
