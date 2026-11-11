# Clock stability

Calculate Allan deviation from receiver clock offsets.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.clock_stability --port /dev/ttyUSB0 --baud 921600 \
    --json out.json
```

Replay the captured TIME data:

```bash
python -m examples.clock_stability --replay /tmp/time.bin
```

## Inputs and results

The analysis needs at least 128 valid TIME samples at regular intervals. Short
or invalid captures produce an `insufficient_data` report and exit status 1.

## Understanding the result

Allan deviation describes clock frequency variation over different averaging
times. `phase_deviation` is tau multiplied by frequency Allan deviation, in
seconds. It is not time deviation (TDEV), which requires modified Allan
deviation.

## References

Riley (2008), NIST SP 1065.
