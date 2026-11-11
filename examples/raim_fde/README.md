# RAIM fault detection and exclusion

Run RAIM fault detection and exclusion, and calculate protection levels.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.raim_fde --port /dev/ttyUSB0 --baud 921600 --json raim.json
```

Replay the supplied capture:

```bash
python -m examples.raim_fde --replay tests/fixtures/captures-live/RANGEA.bin \
    --ephemeris tests/fixtures/captures-live/GPSEPHA.bin \
    --position tests/fixtures/captures-live/BESTPOSA.bin
```

## Inputs and results

Replay needs RANGE observations, GPS ephemeris and an initial position,
supplied in the three files shown. The receiver position must be computed and
within `--position-tolerance` (default one second) of the RANGE epoch. GPS
ephemerides must be healthy, have matching issue numbers and have a reference
time within two hours of transmission. The reported position difference uses
the receiver fix as its reference.

## Understanding the result

The output is experimental and provides no operational integrity guarantee.

## References

Brown (1992), Baseline GPS RAIM.
