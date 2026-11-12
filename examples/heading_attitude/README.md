# Heading and attitude

Calculate heading and pitch from a dual-antenna baseline.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

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
The example requests BSLNENUHD with `ONCHANGED`, so `--interval` does not set a
periodic baseline rate. For periodic heading output, configure a supported log
such as UNIHEADING. See the [output-rate guide](../../README.md#receiver-output-rates).

## References

Unicore N4 R1.4 interface guide.
