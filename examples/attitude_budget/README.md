# Attitude uncertainty

Turns baseline noise into heading and pitch uncertainty.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

Connect to a receiver:

```bash
python -m examples.attitude_budget --port /dev/ttyUSB0 --baud 921600 \
    --timeout 1 --json budget.json
```

Replay the supplied capture:

```bash
python -m examples.attitude_budget \
    --replay tests/fixtures/captures/BSLNENUHDA.bin
```

## Inputs and results

Use a dual-antenna baseline capture for replay. The report estimates heading
and pitch uncertainty from the measured baseline variation.

## Understanding the result

A baseline is the vector between the two antennas. Its geometry and measured
variation determine the estimated uncertainty in heading and pitch. The
estimate does not independently establish the true heading.

## References

Teunissen & Montenbruck (2017), Springer Handbook of GNSS.
