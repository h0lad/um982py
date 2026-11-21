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
FREQJAMSTATUS. A replay with one of these logs reports the available evidence.
The per-report series, fingerprints and alerts include GPS timestamps when
available. The legacy `epoch` fields are sample indices. Detector
classifications describe flag occupancy across bands. RF source and
bandwidth require independent measurements.

## References

Unicore UM982 user manual, JAMSTATUS.
