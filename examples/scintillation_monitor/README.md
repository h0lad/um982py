# Scintillation monitor

Computes the S4 amplitude scintillation index.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

Connect to a receiver:

```bash
python -m examples.scintillation_monitor --port /dev/ttyUSB0 --baud 921600 \
    --frames 120 --interval 1 --window 60 --record captures/cn0.bin \
    --json scintillation.json
```

Replay the supplied capture:

```bash
python -m examples.scintillation_monitor \
    --replay tests/fixtures/captures-live/RANGEA.bin --window 10 \
    --json /tmp/scintillation.json
```

## Inputs and results

`--window` is the number of epochs per S4 window, while `--interval` controls the
epoch spacing for live capture. A useful estimate needs a time series long
enough to fill the chosen window.

## Understanding the result

Scintillation is rapid variation in signal amplitude or phase. This example
calculates an S4 amplitude-variation index from a sequence of receiver
signal-strength observations.

The sampling rate, window length and receiver measurements constrain what can
be observed.

## References

Briggs & Parkin (1963), scintillation.
