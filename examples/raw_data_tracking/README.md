# Raw baseband tracking data

Parse raw baseband containers, inner messages and notices.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.raw_data_tracking --port /dev/ttyUSB0 --baud 921600 \
    --seconds 5 --on-changed --log-port COM1 --record wire.bin \
    --json containers.json
```

Replay the captured raw data:

```bash
python -m examples.raw_data_tracking \
    --replay wire.bin
```

## Inputs and results

Replay requires raw baseband containers, which an ordinary RANGE capture does
not contain. `--raw-log` selects the raw output path, and `--log-port` selects
the receiver output port.

## Understanding the result

The meanings of these fields and their possible I/Q sample formats remain
unverified.

## References

- Unicore N4 R1.4 interface guide.
- observed RAW format.
