# Attitude uncertainty

Estimate heading and pitch uncertainty from baseline noise.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.attitude_budget --port /dev/ttyUSB0 --baud 921600 \
    --timeout 1 --json budget.json
```

Replay the supplied capture:

```bash
python -m examples.attitude_budget \
    --replay tests/fixtures/captures/BSLNENUHDA.bin
```

## Inputs and results

Replay requires a dual-antenna baseline capture.

## References

Teunissen & Montenbruck (2017), Springer Handbook of GNSS.
