# Satellite visibility monitor

Summarize satellite counts, azimuth and elevation by constellation using the
latest SATVIS2 epoch. Add `--csv` to save satellite positions for a sky plot.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.satellite_monitor --port /dev/ttyUSB0 --baud 921600 \
    --json vis.json
```

Replay the supplied capture:

```bash
python -m examples.satellite_monitor \
    --replay tests/fixtures/captures/SATVIS2A.bin --csv sky.csv
```

## Inputs and results

`--duration` and `--interval` control live SATVIS2 collection. Use `--mask` to
set an elevation cutoff in degrees.

## References

Kaplan & Hegarty (2017), Understanding GPS/GNSS.
