# Navigation messages and orbit plots

Generate navigation tables, sky views and orbit figures.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.navigation_messages --port /dev/ttyUSB0 --baud 921600 \
    --output figures --json figures/satellites.json
```

Replay the supplied capture:

```bash
python -m examples.navigation_messages \
    --replay tests/fixtures/captures-live/GPSEPHA.bin --observer 0,0,0 \
    --epoch 399541 --output /tmp/gps-figures
```

## Inputs and results

`--output` selects the figure directory. For replay, supply matching observer
coordinates with `--observer`, the propagation epoch with `--epoch` and a
capture containing the relevant ephemerides. The example coordinates are
placeholders.

## References

- IS-GPS-200.
- Galileo OS SIS ICD.
