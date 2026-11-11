# Baseband command conformance

Send baseband commands and record acknowledgements, rejections and state changes.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

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

Use `--command` to select commands for a live probe. `--window-seconds` sets how
long to wait for notices. `--include-destructive` also sends disruptive commands
and commands with unverified effects. Use it only if you intend those changes.

Without a baseband reply, the JSON `status` is `insufficient_data`. An
application-level acknowledgement alone does not count as a baseband reply.

## References

- Unicore UM982 user manual.
- observed receiver replies.
