# Signal group study

Compare satellites and signals across signal-group settings.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

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

Each `--settings` pair selects master and slave signal-group numbers. A live
study changes the groups and waits for the receiver to reboot. For replay,
`--replay-master` and `--replay-slave` identify the group used in the recording.
The receiver saves each changed group automatically. The study attempts to
restore the original group on exit; interruption or connection failure can
leave another group saved.

## References

Langley (1999), Dilution of Precision.
