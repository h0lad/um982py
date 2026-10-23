# Dilution of precision

Computes DOP values from satellite geometry.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

Connect to a receiver:

```bash
python -m examples.dop_geometry --port /dev/ttyUSB0 --baud 921600 \
    --json dop.json
```

Replay the supplied capture:

```bash
python -m examples.dop_geometry --replay tests/fixtures/captures/SATVIS2A.bin
```

## Inputs and results

The example uses SATVIS2 satellite geometry and compares the computed DOP with
the receiver-reported values. `--mask` excludes satellites below the specified
elevation in degrees.

## Understanding the result

Dilution of precision (DOP) describes how satellite geometry can amplify
measurement errors. Lower DOP generally indicates better geometry, but says
nothing by itself about the size of the underlying measurement errors.

The calculated values can be compared with receiver reports, but differences
may reflect which satellites each calculation includes.

## References

Milliken & Zoller (1978); Kaplan & Hegarty (2017).
