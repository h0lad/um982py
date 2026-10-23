# RAIM fault detection and exclusion

Runs RAIM fault detection, exclusion, and protection levels.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

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
supplied in the three files shown. The calculated fault checks and protection
levels depend on the observations and model assumptions.

## Understanding the result

RAIM checks whether satellite measurements are mutually consistent with a
positioning model. Fault detection and exclusion (FDE) can test whether
removing a measurement improves consistency, whereas protection levels depend on the
chosen assumptions.

The output is an experimental calculation for the available observations, not
an operational integrity guarantee. It requires suitable observation, orbit
and starting-position data.

## References

Brown (1992), Baseline GPS RAIM.
