# Interference monitor

Alerts on jamming, spoofing, and C/N0 dropouts.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

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

The example combines receiver jamming and spoofing indicators with C/N₀
observations. Use `--threshold` to set the C/N₀ alert threshold.

## Understanding the result

Investigate alerts against other evidence. A low C/N₀ or receiver alert can have several
causes, including obstruction or equipment changes, so neither identifies the
source on its own.

## References

Iglewicz & Hoaglin (1993); Unicore UM982 manual.
