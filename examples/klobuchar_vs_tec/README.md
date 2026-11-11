# Klobuchar model and TEC

Compare Klobuchar delay with dual-frequency TEC.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

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

Replay needs RANGE observations and companion ionosphere, satellite-visibility
and position captures. Supply these with `--ionosphere`, `--satvis` and
`--position`.

## Understanding the result

Match the position, visibility, model and observation epochs.

The code-derived delay retains uncalibrated receiver and satellite biases.
The report omits relative differences when that delay is at or below 0.01 m.
The signed and absolute differences remain available in metres.

## References

Klobuchar (1987), single-frequency ionosphere model.
