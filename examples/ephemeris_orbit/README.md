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

Each constellation uses its own ICD constants: `mu = 3.986005e14` for GPS and
`mu = 3.986004418e14` for Galileo/BeiDou; the Earth rotation rate is
`7.2921151467e-5` rad/s for GPS/Galileo and `7.292115e-5` rad/s for BeiDou.
BeiDou GEO satellites (C01-C05, C59-C63) need the additional 5-degree
GK-to-BDCS frame rotation from the BeiDou ICD. GLONASS states are integrated
in PZ-90 with the GLONASS `mu`. Galileo clock polynomials and broadcast group
delays are taken from F/NAV when received, otherwise from I/NAV.

Broadcast time systems differ: BeiDou ephemeris epochs are in BDT, GLONASS
ephemeris epochs in UTC(SU), and the receiver epoch in GPST. Verify the
receiver log's time convention and any leap-second/GPST-BDT offset before
comparing angles or clock biases across constellations.

## References

- IS-GPS-200 (GPS user algorithm and constants).
- Galileo OS SIS ICD (F/NAV and I/NAV clocks, BGDs, constants).
- BeiDou-SIS-ICD-2.0, B1I (GEO 5-degree rotation, constants).
- GLONASS ICD, edition 5.1 (PZ-90 integration).
- RTKLIB `eph2pos` (reference implementation of the BDS GEO user algorithm).
