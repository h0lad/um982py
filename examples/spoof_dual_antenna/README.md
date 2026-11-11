# Dual-antenna spoofing checks

Cross-check heading, visibility and spoof indicators.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

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

## References

- Kaplan & Hegarty (2017).
- Unicore UM982 manual.
