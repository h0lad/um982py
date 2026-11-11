# Coordinate frames

Convert positions and baselines between ECEF, geodetic and local ENU coordinates.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.coordinate_frames --port /dev/ttyUSB0 --baud 921600 \
    --json frames.json
```

Replay a capture:

```bash
python -m examples.coordinate_frames --replay /tmp/coordinates.bin
```

## Inputs and results

BESTXYZ supplies the antenna position and BSLNENUHD supplies the baseline.
Replay requires both logs for the comparison.

The conversions preserve the reference-frame realization and coordinate epoch.

## References

NIMA (2000), WGS84 TR8350.2.
