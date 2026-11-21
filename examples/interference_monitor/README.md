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
The spoof report includes anomaly and frequency masks and the satellite numbers
reported for each constellation. Unknown mask bits remain visible in the masks.
Alerts identify their source log and receiver timestamp when available.
Each log has its own zero-based record index. The C/N₀ score compares each
satellite with its samples across the analysed capture.

## Understanding the result

Low C/N₀ and receiver alerts can also result from obstructions or equipment
changes.

## References

- Iglewicz & Hoaglin (1993).
- Unicore UM982 manual.
