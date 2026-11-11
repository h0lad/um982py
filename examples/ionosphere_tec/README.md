# Ionospheric TEC

Calculate slant TEC, ROT and ROTI from dual-frequency ranges.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

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
`--secondary-frequency` select the carrier frequencies. ROT and ROTI summarize
TEC change over time and require continuous observations.

## Understanding the result

Code and levelled-phase TEC values still contain receiver and satellite
differential code biases. They estimate TEC variation, not calibrated absolute
TEC. Signal or lock changes, gaps and failed Doppler-phase closure split the
carrier arcs.

ROTI needs a complete five-minute arc with regular samples. When replaying
data, set `--interval` to the recorded cadence.

## References

Misra & Enge (2011), Global Positioning System.
