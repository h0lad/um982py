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

The figures use each constellation's ICD gravitational constant, and GLONASS
orbital elements are derived with the PZ-90 `mu`. BeiDou GEO states use the
ICD 5-degree frame rotation. These are propagation illustrations, not
validated navigation solutions.

## References

- IS-GPS-200.
- Galileo OS SIS ICD.
- BeiDou-SIS-ICD-2.0 (B1I).
- GLONASS ICD, edition 5.1.
