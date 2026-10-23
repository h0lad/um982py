# User equivalent range error

Estimates user range error from position uncertainty and DOP.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

Connect to a receiver:

```bash
python -m examples.uere_budget --port /dev/ttyUSB0 --baud 921600 \
    --json uere.json
```

Replay a capture:

```bash
python -m examples.uere_budget --replay /tmp/uere.bin
```

## Inputs and results

The calculation combines position uncertainty with dilution of precision. It is
an estimate based on receiver data, not an independent measurement of range
error.

## Understanding the result

User equivalent range error (UERE) is a summary estimate of measurement error
expressed as an equivalent range error. This example combines receiver
position uncertainty and dilution of precision (DOP), a geometry factor.

The calculation inherits assumptions and uncertainty from the receiver and
geometry. It is not an independent measurement of the actual ranging error.

## References

Kaplan & Hegarty (2017), Understanding GPS/GNSS.
