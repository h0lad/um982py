# Baseband command conformance

Sends baseband commands and records ACKs, rejects, and state changes.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

Connect to a receiver:

```bash
python -m examples.baseband_conformance --port /dev/ttyUSB0 --baud 921600 \
    --command RFSPIREAD --rf-address 0 --duration 15 --json rf-read.json
```

Replay a capture:

```bash
python -m examples.baseband_conformance --replay notices.bin --json out.json
```

## Inputs and results

Use `--command` to restrict a live probe and `--window-seconds` to control the
notice window. `--include-destructive` also probes disruptive commands and
commands with unverified effects, so use it only when those state changes are
intended.
The JSON `status` reports `insufficient_data` if a command has no baseband
reply, even if its application-level request was acknowledged.

## Understanding the result

The baseband is the receiver subsystem that processes radio signals. This
diagnostic sends selected baseband commands and compares application
acknowledgements with observed baseband replies or state changes.

## References

Unicore UM982 user manual; observed receiver replies.
