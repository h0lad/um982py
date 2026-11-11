# Empirical C/N₀ elevation pattern

Fit a range-normalized C/N₀ curve for one signal. To compare helix and patch
antennas, use `dual_antenna_rf_audit`.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

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

Select the RANGE system and signal with `--system` and `--signal` (default:
GPS L1 C/A). Use `--csv` to write the fitted elevation curve and `--json` to
write the report.

## Understanding the result

Antenna, cable, receiver and surroundings affect the measured C/N₀. The curve
is not a calibrated antenna gain measurement.

## References

Kaplan & Hegarty (2017), *Understanding GPS/GNSS*.
