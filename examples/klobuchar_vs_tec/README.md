# Klobuchar model and TEC

Compares Klobuchar delay with dual-frequency TEC.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

Connect to a receiver:

```bash
python -m examples.klobuchar_vs_tec --port /dev/ttyUSB0 --baud 921600 \
    --json ionosphere.json
```

Replay the supplied capture:

```bash
python -m examples.klobuchar_vs_tec \
    --replay tests/fixtures/captures-live/RANGEA.bin \
    --ionosphere tests/fixtures/captures-live/GPSIONA.bin \
    --satvis tests/fixtures/captures-live/SATVIS2A.bin \
    --position tests/fixtures/captures-live/BESTPOSA.bin
```

## Inputs and results

Replay requires RANGE observations and companion ionosphere,
satellite-visibility and position captures, supplied by `--ionosphere`,
`--satvis` and `--position`.

## Understanding the result

The Klobuchar model estimates ionospheric delay from parameters broadcast by
GPS. This example compares that estimate with one derived from two-frequency
observations. Match the position, visibility, model and observation epochs.
Both estimates rely on assumptions, so agreement does not independently establish
the true delay.

## References

Klobuchar (1987), single-frequency ionosphere model.
