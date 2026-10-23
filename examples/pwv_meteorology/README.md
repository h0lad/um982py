# Precipitable water vapour

Derives precipitable water vapour from zenith wet delay.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

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

## Understanding the result

Water vapour delays GNSS signals travelling through the atmosphere. This
example derives an estimate of precipitable water vapour from a zenith wet
delay and an assumed water-vapour-weighted temperature.

The estimate depends on the input delay and temperature model.

## References

Bevis et al. (1992), GPS meteorology.
