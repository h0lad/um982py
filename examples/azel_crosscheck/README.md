# Azimuth and elevation cross-check

Compare azimuth and elevation from broadcast orbits with the receiver's SATVIS2
angles.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.azel_crosscheck --port /dev/ttyUSB0 --baud 921600 \
    --json azel.json
```

Replay the supplied capture:

```bash
python -m examples.azel_crosscheck \
    --replay tests/fixtures/captures-live/SATVIS2A.bin \
    --position tests/fixtures/captures-live/BESTPOSA.bin \
    --ephemeris tests/fixtures/captures-live/GPSEPHA.bin
```

## Inputs and results

Replay needs SATVIS2 data, a position capture passed as `--position` and an
ephemeris capture passed as `--ephemeris`.
The observer position must be computed and lie within `--position-tolerance`
(default one second) of the selected SATVIS2 epoch. Antenna selection applies
equally to live and replayed positions.

## Understanding the result

Match position, orbit and visibility data by time and satellite. This checks
consistency with receiver-reported angles, not independent orbit accuracy.
Supply an ephemeris set appropriate to the observation period; this example
does not implement navigation-message health/age selection for every
constellation. No matched satellites returns `insufficient_data` and exit code 1.

## References

- IS-GPS-200N.
- Unicore N4 R1.4 interface guide.
