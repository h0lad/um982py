# Clock jump analysis

Find code and carrier jumps that appear together across satellites.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.clock_jump_forensics --port /dev/ttyUSB0 --baud 921600 \
    --duration 300 --record captures/clock.bin --json clock-jumps.json
```

Replay the supplied capture:

```bash
python -m examples.clock_jump_forensics \
    --replay tests/fixtures/specialist/rtklib-motion.bin \
    --json /tmp/clock-jumps.json
```

## Inputs and results

`--threshold` sets the minimum common range jump in metres, and `--agreement`
sets the consensus half-width in metres.

## References

Unicore N4 R1.4 interface guide.
