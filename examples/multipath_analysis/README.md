# Multipath analysis

Calculate RMS code-minus-carrier residuals as a multipath proxy.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.multipath_analysis --port /dev/ttyUSB0 --baud 921600 \
    --json out.json
```

Replay the supplied capture:

```bash
python -m examples.multipath_analysis \
    --replay tests/fixtures/captures/RANGEB.bin
```

## Inputs and results

Replay or capture RANGE observations over time. `--frequency` selects the
carrier frequency and `--frames` bounds the number of epochs.

## Understanding the result

Reflected signals affect code and carrier measurements. Code-minus-carrier
residuals include these site effects along with ionospheric variation and
receiver noise. Their RMS is a proxy for multipath, without a calibrated error
budget or a map of reflectors.

Before detrending, the analysis splits carrier arcs by signal identity, lock
time, cadence and Doppler-phase closure. When replaying data, set `--interval`
to the capture cadence.

## References

Braasch (1996), Multipath effects.
