# Azimuth and elevation cross-check

Checks broadcast-orbit azimuth and elevation against SATVIS2.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

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

Replay needs a SATVIS2 capture plus the companion `--position` and
`--ephemeris` captures shown below. The report compares receiver visibility
angles with angles calculated from the broadcast orbit and observer position.

## Understanding the result

Azimuth is a satellite's compass direction, while elevation is its angle above the
horizon. This example calculates those angles from a receiver position and
broadcast satellite orbit, then compares them with the receiver's SATVIS2
report.

A useful comparison requires position, orbit and visibility data for matching
times and satellites. Differences can result from mismatched inputs as well as
model or receiver differences.

## References

IS-GPS-200N; Unicore N4 R1.4 interface guide.
