# Elevation mask optimizer

Find the elevation mask with the best satellite geometry.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.elevation_optimizer --port /dev/ttyUSB0 --baud 921600 \
    --minimum-satellites 8 --json mask.json
```

Replay the supplied capture:

```bash
python -m examples.elevation_optimizer \
    --replay tests/fixtures/captures/SATVIS2B.bin
```

## Inputs and results

`--minimum-satellites` sets the minimum satellite count for candidate masks.
`--ceiling` sets the highest mask to consider, in degrees.

The selected mask applies to the captured sky geometry.

## References

Kaplan & Hegarty (2017), Understanding GPS/GNSS.
