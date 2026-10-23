# Multipath analysis

Measures code-minus-carrier multipath RMS.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

Connect to a receiver:

```bash
python -m examples.multipath_analysis --port /dev/ttyUSB0 --baud 921600 \
    --json out.json
```

Replay the supplied capture:

```bash
python -m examples.multipath_analysis \
    --replay tests/fixtures/captures/RANGEB.bin
```

## Inputs and results

Replay or capture RANGE observations over time. `--frequency` selects the
carrier frequency and `--frames` bounds the number of epochs. The
code-minus-carrier statistic is affected by the measurement arc and site.

## Understanding the result

Multipath occurs when reflected satellite signals reach the antenna alongside
the direct signal, affecting code and carrier measurements. The example
summarizes a code-minus-carrier statistic that includes site and measurement
effects without directly mapping reflectors or providing a calibrated error
budget.

## References

Braasch (1996), Multipath effects.
