# Clock stability

Computes Allan deviation from receiver clock offsets.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

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

The analysis needs at least 128 valid TIME samples at a regular cadence, so set
`--duration` and `--interval` to collect enough epochs. Short or invalid captures
produce an `insufficient_data` report and exit status 1.

## Understanding the result

Allan deviation describes how clock frequency varies over different averaging
times. The result characterizes the captured receiver clock under the analysis
assumptions. It does not calibrate an external time standard.

## References

Riley (2008), NIST SP 1065.
