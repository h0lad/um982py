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

The calculation uses unweighted SATVIS2 geometry with one clock state per
constellation. The output also includes the shared-clock calculation for
comparison. `--mask` excludes satellites below the given elevation in degrees
when a matched receiver DOP report does not supply a mask.

DOP does not measure the underlying errors. Differences from receiver reports
may reflect different satellite selections, weights and clock models. GDOP and
TDOP include all estimated clock states. For a multi-constellation fit the
example leaves their receiver differences blank.

## References

- Milliken & Zoller (1978).
- Kaplan & Hegarty (2017).
