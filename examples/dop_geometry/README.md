# Dilution of precision

Calculate DOP values from satellite geometry.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.dop_geometry --port /dev/ttyUSB0 --baud 921600 \
    --json dop.json
```

Replay the supplied capture:

```bash
python -m examples.dop_geometry --replay tests/fixtures/captures/SATVIS2A.bin
```

## Inputs and results

The calculation uses SATVIS2 geometry and compares DOP with receiver-reported
values. `--mask` excludes satellites below the given elevation in degrees.

DOP does not measure the underlying errors. Differences from receiver reports
may reflect different satellite selections.

## References

- Milliken & Zoller (1978).
- Kaplan & Hegarty (2017).
