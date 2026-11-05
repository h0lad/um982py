# User equivalent range error

Estimates user range error from position uncertainty and DOP.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the repository root.

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

The calculation pairs computed SINGLE PSRPOS fixes and PSRDOP at the same
epoch. Because the logs do not establish that both used the same satellite set,
the calculation requires `--assume-matched-geometry` after independent review.
The inversion also assumes unweighted geometry and equal independent range
errors. Without the assertion, the example reports insufficient data.

## Understanding the result

User equivalent range error (UERE) is a summary estimate of measurement error
expressed as an equivalent range error. This example combines receiver
position uncertainty and dilution of precision (DOP), a geometry factor.

The reported pseudorange sigma is a receiver measurement diagnostic, not total
UERE or independent validation of the position-derived estimate.

## References

Kaplan & Hegarty (2017), Understanding GPS/GNSS.
