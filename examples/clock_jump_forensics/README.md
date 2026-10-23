# Clock jump analysis

Flags code and carrier jumps that appear together across satellites.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

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
sets the consensus half-width in metres. A flag identifies a common
discontinuity in the observations, but does not establish its cause.

## Understanding the result

The example looks for range changes occurring together across several
satellites, which can indicate a receiver clock discontinuity or another shared
effect. Provide a sufficiently long capture and review flagged times against
other logs before attributing a cause.

## References

Unicore N4 R1.4 interface guide.
