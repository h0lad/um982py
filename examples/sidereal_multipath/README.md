# Sidereal multipath

Check whether multipath repeats after one sidereal day.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.sidereal_multipath --training captures/day1.bin \
    --port /dev/ttyUSB0 --baud 921600 --duration 3600 \
    --record captures/day2.bin --json repeatability.json
```

Replay the supplied capture:

```bash
python -m examples.sidereal_multipath \
    --replay tests/fixtures/specialist/repeat-validation.bin \
    --training tests/fixtures/specialist/repeat-training.bin \
    --json /tmp/repeatability.json
```

## Inputs and results

Set `--training` to an earlier RANGE and SATVIS2 capture from the same
stationary site. The live or replay input is the comparison pass. Use
`--cell-degrees` and `--minimum-cell-samples` to control the sky bins.

## Understanding the result

Keep the antenna and surroundings comparable between captures.

## References

Axelrad, Larson & Jones (2005), sidereal repeat.
