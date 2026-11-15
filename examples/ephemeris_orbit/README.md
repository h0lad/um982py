# Broadcast ephemeris orbits

Propagate broadcast ephemerides for four constellations.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

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

`--seconds` sets the propagation offset from each ephemeris's own reference
time, not a common absolute epoch. Replay requires broadcast ephemerides.
The supplied fixture contains GPS ephemerides only.

Each output state includes its broadcast satellite identifier. No usable
ephemerides produces `insufficient_data` and exit code 1. This is a propagation
demonstration: it does not select healthy, age-valid ephemerides for a position
solution or estimate orbit uncertainty. Use `broadcast_orbit_audit` to compare
broadcast and precise products at matched epochs.

## References

- IS-GPS-200.
- Galileo OS SIS ICD.
- GLONASS ICD.
