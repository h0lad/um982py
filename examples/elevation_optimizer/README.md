# Elevation mask optimizer

Find the highest elevation mask that meets the chosen geometry constraints.

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
`--max-pdop` bounds the unweighted PDOP, computed with one receiver clock per
constellation (default 6; a large value such as `--max-pdop 1000` bounds only the satellite
count).
Without a PDOP bound the highest mask keeps only the minimum number of
satellites, which on 2026-11-24 meant a 57° mask with PDOP 131.
The report includes the mask sweep and geometry epoch for comparison.

The selected mask applies to the captured sky geometry.

## References

Kaplan & Hegarty (2017), Understanding GPS/GNSS.
