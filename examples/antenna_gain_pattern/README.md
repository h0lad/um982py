# Empirical C/N₀ elevation pattern

Fits a range-normalized C/N₀ curve for one signal, including site and RF-path
effects. For a helix/patch comparison, use `dual_antenna_rf_audit`.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

Connect to a receiver:

```bash
python -m examples.antenna_gain_pattern --port /dev/ttyUSB0 --baud 921600 \
    --duration 300 --system 0 --signal 0 --record /tmp/sky.bin \
    --csv /tmp/pattern.csv --json /tmp/pattern.json
```

Replay a capture:

```bash
python -m examples.antenna_gain_pattern --replay /tmp/sky.bin \
    --csv /tmp/replay-pattern.csv --json /tmp/replay-pattern.json
```

## Inputs and results

Select the RANGE system and signal with `--system` and `--signal`, which default
to GPS L1 C/A. `--csv` writes the fitted elevation curve, while `--json`
writes the report. The curve describes received signal strength at this site,
not calibrated antenna gain.

## Understanding the result

The example groups receiver-reported C/N₀ observations by satellite signal and
elevation, then fits a curve to the recorded data. Because the curve includes the
antenna, cable, receiver and surroundings, it helps compare a particular setup
but does not provide a calibrated antenna gain measurement.

## References

Kaplan & Hegarty (2017), *Understanding GPS/GNSS*.
