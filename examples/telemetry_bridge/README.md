# Telemetry bridge

Streams decoded frames as newline-delimited JSON.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

Connect to a receiver:

```bash
python -m examples.telemetry_bridge --port /dev/ttyUSB0 --baud 921600 \
    --seconds 30 --json telemetry.ndjson
```

Replay the supplied capture:

```bash
python -m examples.telemetry_bridge --replay tests/fixtures/versiona.bin
```

## Inputs and results

`--seconds` sets the live streaming duration, and `--json` writes
newline-delimited JSON to a file. Replay reads an existing wire capture instead
of opening the receiver.

## Understanding the result

The bridge decodes receiver messages into newline-delimited JSON for scripts and
log pipelines, using either a live receiver or a recorded binary capture. Choose
an appropriate output path and collection time, and protect the telemetry file
if its messages contain position data.

## References

Unicore N4 R1.4 interface guide.
