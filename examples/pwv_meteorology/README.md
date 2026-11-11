# Precipitable water vapour

Estimate precipitable water vapour from zenith wet delay.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.pwv_meteorology --port /dev/ttyUSB0 --baud 921600 \
    --json pwv.json
```

Run the published demonstration without a receiver:

```bash
python -m examples.pwv_meteorology --manual
```

## Inputs and results

`--tm` sets the water-vapour-weighted mean temperature in kelvin. The
`--manual` option uses published demonstration values instead of receiver data.

## References

Bevis et al. (1992), GPS meteorology.
