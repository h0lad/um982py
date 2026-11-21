# RAIM fault detection and exclusion

Demonstrate residual chi-square fault detection, exclusion and single-fault
position-error slope bounds.

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

The solver uses one independent GPS L1 measurement per satellite and one
receiver clock state. Its Python API rejects duplicate satellites and mixed
constellations; a multi-constellation solver needs inter-system bias states.

The legacy `protection_levels.hpl` and `vpl` fields contain the maximum
single-fault position-error slopes multiplied by the square root of the
residual detection threshold. They do not include a missed-detection
probability, multiple-fault risk allocation or calibrated measurement-error
overbounds. They are teaching quantities, not operational protection levels.
The default pseudorange sigmas come from the receiver. An atmospheric
modelling error can trigger alarms or mask faults. Use `--range-model-sigma`
to add independently justified range uncertainty in quadrature.

`alarm` describes the initial residual test. At each exclusion step the
example refits leave-one-out sets in descending order of the weighted residual
of the removed observation. It takes the first set that passes the test, or
the set with the smallest statistic if none passes. `integrity_passed`
describes the remaining set.
Exit code 0 means the report was computed. Inspect both fields.

## References

Brown (1992), Baseline GPS RAIM.

[ESA Navipedia: RAIM fundamentals](https://gssc.esa.int/navipedia/index.php/RAIM_Fundamentals).
