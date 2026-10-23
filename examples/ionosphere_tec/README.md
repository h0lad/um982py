# Ionospheric TEC

Computes slant TEC, ROT, and ROTI from dual-frequency ranges.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

Connect to a receiver:

```bash
python -m examples.ionosphere_tec --port /dev/ttyUSB0 --baud 921600 \
    --json out.json
```

Replay the supplied capture:

```bash
python -m examples.ionosphere_tec --replay tests/fixtures/captures/RANGEB.bin
```

## Inputs and results

The calculation needs dual-frequency RANGE observations. `--frequency` and
`--secondary-frequency` select carrier frequencies, while ROT and ROTI require a time
series, not just one epoch.

## Understanding the result

Charged particles in the ionosphere delay satellite signals. Comparing two
frequencies estimates variation in total electron content (TEC) along a signal
path, while ROT and ROTI summarize its change over time and therefore need
sufficient continuous observations. The result depends on the selected
frequencies and processing assumptions.

## References

Misra & Enge (2011), Global Positioning System.
