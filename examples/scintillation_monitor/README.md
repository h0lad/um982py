# Scintillation monitor

Estimate an uncalibrated S4-like proxy from receiver C/N₀.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.scintillation_monitor --port /dev/ttyUSB0 --baud 921600 \
    --duration 130 --frames 120 --interval 1 --window 60 \
    --record captures/cn0.bin --json scintillation.json
```

Replay the supplied capture:

```bash
python -m examples.scintillation_monitor \
    --replay tests/fixtures/captures-live/RANGEA.bin --window 10 \
    --json /tmp/scintillation.json
```

## Inputs and results

`--window` sets the maximum number of epochs per calculation. `--interval`
sets the requested live output interval. Live capture stops at the frame or
duration limit, whichever comes first. Collect enough epochs to fill the window.

The receiver filters C/N₀. The calculation does not remove trends or correct
for thermal noise.

## References

Briggs & Parkin (1963), scintillation.
