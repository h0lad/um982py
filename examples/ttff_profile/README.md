# Time to first fix

Measures time to first fix after cold or warm starts.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

Connect to a receiver:

```bash
python -m examples.ttff_profile --port /dev/ttyUSB0 --baud 921600 --start cold \
    --runs 3 --json out.json
```

Replay the supplied capture:

```bash
python -m examples.ttff_profile \
    --replay tests/fixtures/captures-live/BESTPOSA.bin --start warm \
    --json out.json
```

## Inputs and results

`--start` selects cold or warm starts, and `--runs` sets the number of live
trials. Live trials issue receiver reset commands. Replay evaluates the
captured epochs and does not perform a new start.

## Understanding the result

Time to first fix (TTFF) is the elapsed time until a receiver reports a
position after a selected start. This example runs repeated starts or analyzes
a previously recorded sequence.

Live cold or warm starts issue receiver reset commands and interrupt its
current operation. Sky view, stored data, configuration and timeouts affect
the result, whereas replay does not perform a new reset.

## References

Unicore UM982 user manual, reset and startup.
