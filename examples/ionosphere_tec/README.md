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

ROTI needs a complete five-minute arc with regular samples. The reported index
is the sample standard deviation (`n-1` denominator) of ROT in TECU/min; other
processing chains use the population form, so do not compare thresholds across
implementations without checking this. When replaying data, set `--interval` to
the recorded cadence.

The slant TEC proxy is `(P_low - P_high) f_low^2 f_high^2 / (40.3 (f_high^2 -
f_low^2))` in electrons/m², divided by 10^16 for TECU; one TECU corresponds to
about 0.105 m of GPS L1/L2 differential code delay. Carrier phases use the
native RANGE sign convention (phase decreases as range increases), so levelling
the phase-derived TEC to the code TEC keeps the same sign. RANGE phase and
Doppler must come from one continuous, slip-free arc.

## References

- Misra & Enge (2011), *Global Positioning System: Signals, Measurements and
  Performance*.
- Pi et al. (1997), *Monitoring of global ionospheric irregularities using the
  Worldwide GPS Network*, Geophysical Research Letters 24(18), 2283-2286 (ROT
  and the five-minute ROTI definition).
- [ESA Navipedia: Combining pairs of signals and clock definition](https://gssc.esa.int/navipedia/index.php/Combining_pairs_of_signals_and_clock_definition).
