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
Replay requires computed, finite positions and a computed baseline from the
same observation period. `--position-tolerance` limits their epoch offset
(default one second). Concatenating unrelated single-frame fixtures is not a
valid measurement pair.

The reported residual is an ENU → ECEF → ENU round trip using the same input
baseline. It checks the coordinate conversion, not measured baseline accuracy.
The baseline always runs from physical ANT1 to ANT2 in the ANT1 local frame;
when ANT2 is selected (including `--swap-antennas`), a matching primary
BESTNAVXYZ origin is required. The report identifies both this direction and
the position epoch offset.

The conversions preserve the reference-frame realization and coordinate epoch.

## References

NIMA (2000), WGS84 TR8350.2.
