# Heading and attitude

Turns a dual-antenna baseline into heading and pitch.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

Connect to a receiver:

```bash
python -m examples.heading_attitude --port /dev/ttyUSB0 --baud 921600 \
    --json attitude.json
```

Replay the supplied capture:

```bash
python -m examples.heading_attitude \
    --replay tests/fixtures/captures/BSLNENUHDB.bin
```

Swap the antenna roles:

```bash
python -m examples.heading_attitude --port /dev/ttyUSB0 --swap-antennas \
    --json attitude-swapped.json
```

## Inputs and results

The example requires a dual-antenna baseline. If the antenna roles are reversed,
`--swap-antennas` changes the baseline interpretation without changing RF power.

## Understanding the result

Heading and pitch are derived from the baseline vector between the antennas, so
their interpretation depends on antenna placement and which antenna is primary.
Connect both antennas or replay baseline records. Swapping roles changes the
interpreted vector, not the physical wiring.

## References

Unicore N4 R1.4 interface guide.
