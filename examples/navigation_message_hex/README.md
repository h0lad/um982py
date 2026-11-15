# Navigation messages in hex

Display navigation messages as annotated hex.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.navigation_message_hex --port /dev/ttyUSB0 --baud 921600 \
    --seconds 20
```

Replay the supplied capture:

```bash
python -m examples.navigation_message_hex \
    --replay tests/fixtures/captures-live/GPSEPHB.bin --seconds 2
```

## Inputs and results

Use `--family` or `--log` to select messages and `--seconds` to set the live
collection time.
For example, `--log PPSSTATUS` or `--log SPOOFINFO` annotates the documented
status fields and marks reserved bytes separately.

Without `--json`, stdout is a single JSON report and the annotated human-readable
dump goes to stderr. With `--json FILE`, the report goes to the file and the dump
goes to stdout.

## References

Unicore N4 R1.4 interface guide.
