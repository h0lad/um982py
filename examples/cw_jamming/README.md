# Continuous-wave jamming

Classify continuous-wave jamming from JAMSTATUS and FREQJAMSTATUS.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.cw_jamming --port /dev/ttyUSB0 --baud 921600 \
    --json jam.json
```

Replay a capture:

```bash
python -m examples.cw_jamming --replay /tmp/jam.bin
```

## Inputs and results

Choose a capture duration and interval long enough to include both JAMSTATUS and
FREQJAMSTATUS. A replay must contain both messages.

## References

Unicore UM982 user manual, JAMSTATUS.
