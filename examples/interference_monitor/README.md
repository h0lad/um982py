# Interference monitor

Monitor jamming, spoofing and C/N₀ dropout alerts.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.interference_monitor --port /dev/ttyUSB0 --baud 921600 \
    --json alerts.json
```

Replay the supplied capture:

```bash
python -m examples.interference_monitor \
    --replay tests/fixtures/captures/RANGEB.bin
```

## Inputs and results

Use `--threshold` to set the C/N₀ alert threshold.

## Understanding the result

Low C/N₀ and receiver alerts can also result from obstructions or equipment
changes.

## References

- Iglewicz & Hoaglin (1993).
- Unicore UM982 manual.
