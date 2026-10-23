# Elevation mask optimizer

Finds the elevation mask with the best satellite geometry.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

Connect to a receiver:

```bash
python -m examples.elevation_optimizer --port /dev/ttyUSB0 --baud 921600 \
    --minimum-satellites 8 --json mask.json
```

Replay the supplied capture:

```bash
python -m examples.elevation_optimizer \
    --replay tests/fixtures/captures/SATVIS2B.bin
```

## Inputs and results

`--minimum-satellites` sets the minimum satellite count for candidate masks,
and `--ceiling` bounds the mask search. The selected geometry depends on the
observed sky.

## Understanding the result

An elevation mask sets the minimum angle above the horizon for including a
satellite. Raising it excludes more low-elevation satellites and can reduce
their number and geometric spread. The example compares candidate masks against
the captured geometry and a minimum satellite count. The selected mask applies
to that observation.

## References

Kaplan & Hegarty (2017), Understanding GPS/GNSS.
