# Satellite visibility monitor

Summarizes the latest SATVIS2 epoch by constellation, including satellite
counts, azimuth and elevation. An optional CSV contains the satellite positions
for a sky plot.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

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

The live example writes JSON to `vis.json`, while the replay example writes sky-plot
data to `sky.csv`.

## Inputs and results

`--duration` and `--interval` control live SATVIS2 collection. The report uses
the latest receiver epoch, and `--mask` applies an elevation cutoff in degrees.

## Understanding the result

The JSON summarizes the satellites and directions at the latest captured epoch.
The optional CSV supports a sky plot using azimuth (compass direction) and
elevation (angle above the horizon). Visibility or a high satellite count
alone does not establish position accuracy.

## References

Kaplan & Hegarty (2017), Understanding GPS/GNSS.
