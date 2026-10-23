# Coordinate frames

Converts between ECEF, geodetic, ENU, and baselines.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

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

The example uses BESTXYZ for the antenna position and BSLNENUHD for the
baseline. Replay requires both logs to compare the receiver baseline with the
converted coordinates.

## Understanding the result

The example compares geodetic latitude, longitude and ellipsoidal height with
Earth-centred ECEF coordinates and a local east/north/up vector. These
calculations change the coordinate representation without changing the
reference-frame realization or epoch.

## References

NIMA (2000), WGS84 TR8350.2.
