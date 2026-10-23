# Sidereal multipath

Checks whether multipath repeats after one sidereal day.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

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

`--training` must point to an earlier RANGE and SATVIS2 capture from the same
stationary site. The live or replay input is the comparison pass, and
`--cell-degrees` and `--minimum-cell-samples` control the sky bins.

## Understanding the result

Satellite geometry can repeat at approximately a sidereal-day interval, making
some site-dependent reflected-signal patterns repeat. This example compares
observations from an earlier capture and a later pass at the same site.

Keep the antenna and surroundings comparable and provide enough matched
samples. A repeated pattern is evidence for investigation.

## References

Axelrad, Larson & Jones (2005), sidereal repeat.
