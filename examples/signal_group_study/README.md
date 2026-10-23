# Signal group study

Compares satellites and signals across signal-group settings.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

Connect to a receiver:

```bash
python -m examples.signal_group_study --port /dev/ttyUSB0 --baud 921600 \
    --settings 4 5 --settings 3 6 --json out.json
```

Replay a capture:

```bash
python -m examples.signal_group_study --replay live.bin --json out.json
```

## Inputs and results

Each `--settings` pair specifies master and slave signal-group numbers. A live
study changes signal groups and waits for the receiver to reboot, while the replay
options identify the group used for a recorded transcript.

## Understanding the result

A signal group is a receiver configuration selecting combinations of satellite
signals and antenna roles. This example compares observed satellites and
signals for selected group pairs.

The live study changes receiver settings and can reboot the receiver. Run it
only when that interruption is acceptable. Replay analyzes previously captured
data instead.

## References

Langley (1999), Dilution of Precision.
