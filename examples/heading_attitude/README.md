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

## Library usage

### Get the direction of a vehicle

With two rigidly mounted antennas, read the heading of their baseline:

```python
from um982py import Receiver

with Receiver.serial("/dev/ttyUSB0", 921600) as receiver:
    heading = receiver.heading()

if heading.valid:
    print(f"Heading: {heading.degrees:.1f}° clockwise from true north")
else:
    print("Dual-antenna heading is not available yet")
```

Apply the measured antenna mounting offset if the baseline is not aligned with
the vehicle's forward direction.

## References

Unicore N4 R1.4 interface guide.
