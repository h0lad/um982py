# Raw baseband tracking data

Parses raw baseband containers, inner messages, and notices.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

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

The diagnostic inspects baseband containers, their inner binary messages and
notice records. Field meanings and possible I/Q sample formats remain
unverified hypotheses rather than established signal measurements.

## References

Unicore N4 R1.4 interface guide; observed RAW format.
