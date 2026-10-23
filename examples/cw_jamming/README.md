# Continuous-wave jamming

Classifies continuous-wave jamming from JAMSTATUS and FREQJAMSTATUS.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

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

## Understanding the result

Continuous-wave interference is concentrated around a narrow frequency range.
The example summarizes receiver diagnostics that may indicate such interference,
but its classification reflects only the captured interval and does not locate
a transmitter or establish intent.

## References

Unicore UM982 user manual, JAMSTATUS.
