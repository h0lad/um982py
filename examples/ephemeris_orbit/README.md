# Broadcast ephemeris orbits

Propagates broadcast ephemerides for four constellations.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

Connect to a receiver:

```bash
python -m examples.ephemeris_orbit --port /dev/ttyUSB0 --baud 921600 \
    --seconds 20 --json orbits.json
```

Replay the supplied capture:

```bash
python -m examples.ephemeris_orbit \
    --replay tests/fixtures/captures/GPSEPHA.bin --seconds 0
```

## Inputs and results

`--seconds` sets the propagation offset. Replay requires broadcast ephemeris,
and the supplied fixture contains GPS ephemeris only.

## Understanding the result

The example calculates satellite positions at the chosen offset from broadcast
ephemerides, so the output depends on the validity of those records and the
selected epoch.

## References

IS-GPS-200; Galileo OS SIS ICD; GLONASS ICD.
