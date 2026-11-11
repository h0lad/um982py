# Telemetry bridge

Stream decoded frames as newline-delimited JSON.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

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

`--seconds` sets the live streaming duration, and `--json` writes to a file.
Replay decodes the capture incrementally. Live capture buffers frames in a
fixed-size queue. If output cannot keep up, the bridge reports dropped frames
and exits with status 1. A receiver disconnect also stops the bridge with an error.

## References

Unicore N4 R1.4 interface guide.
