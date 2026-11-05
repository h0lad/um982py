# Weighted least-squares position

Solves a position from pseudoranges with weighted least squares.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the repository root.

Connect to a receiver:

```bash
python -m examples.wls_position --port /dev/ttyUSB0 --baud 921600 \
    --json position.json
```

Replay the supplied capture:

```bash
python -m examples.wls_position \
    --replay tests/fixtures/captures-live/RANGEA.bin \
    --ephemeris tests/fixtures/captures-live/GPSEPHA.bin \
    --position tests/fixtures/captures-live/BESTPOSA.bin
```

## Inputs and results

Replay needs RANGE, GPS ephemeris and an initial position, supplied in the
three captures shown.
The receiver position must be computed and within `--position-tolerance`
(default one second) of the RANGE epoch. GPS ephemerides must be healthy,
have matching issue numbers and have a reference time within two hours of
transmission. The output compares against the receiver position, not surveyed
truth; formal covariance excludes unmodelled errors.

## Understanding the result

Weighted least squares fits satellite pseudoranges using observation weights.
The measurements also contain clock and other errors. The solution depends on
the available satellites, broadcast data, weights and model. Compare it with
independent truth when accuracy matters.

## References

Kaplan & Hegarty (2017), Understanding GPS/GNSS.
