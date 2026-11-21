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

Match position, orbit and visibility data by time and satellite. The example
chooses the nearest ephemeris reference time per satellite within 30 minutes
for GLONASS or two hours for the other constellations. It uses a 2° separation
between lines of sight for the tolerance check so that azimuth near the zenith
does not dominate the result. Raw azimuth and elevation residuals are still
reported. Supply healthy ephemerides for the observation week.
No matched satellites returns `insufficient_data` and exit code 1.

Propagation uses each constellation's ICD constants, the BeiDou GEO rotation
and the available Galileo F/NAV or I/NAV clock set. Constellation time systems
are not converted: verify the BDT/UTC(SU) to GPST offset before comparing
computed and receiver-reported angles for BeiDou or GLONASS.

## References

- IS-GPS-200N.
- Galileo OS SIS ICD.
- BeiDou-SIS-ICD-2.0 (B1I).
- GLONASS ICD, edition 5.1.
- Unicore N4 R1.4 interface guide.
