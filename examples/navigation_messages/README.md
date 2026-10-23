# Navigation messages and orbit plots

Builds navigation tables, sky views, and orbit figures.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

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

`--output` selects the figure directory. For replay, supply observer
coordinates with `--observer` and the propagation epoch with `--epoch`. The
capture must contain the relevant navigation records.

## Understanding the result

This example turns available navigation records into tables and visualizations
of satellite orbits and sky positions. A sky plot shows satellite directions
as seen from a specified observer.

The observer position, time and available ephemerides determine the result.
For replay, provide matching inputs and treat the sample coordinates as
placeholders unless they describe your site.

## References

IS-GPS-200; Galileo OS SIS ICD.
