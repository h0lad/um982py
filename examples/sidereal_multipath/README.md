# Sidereal multipath

Check whether multipath repeats after one sidereal day.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.sidereal_multipath --training captures/day1.bin \
    --port /dev/ttyUSB0 --baud 921600 --duration 3600 \
    --record captures/day2.bin --json repeatability.json
```

Replay the supplied capture:

```bash
python -m examples.sidereal_multipath \
    --replay tests/fixtures/specialist/repeat-validation.bin \
    --training tests/fixtures/specialist/repeat-training.bin \
    --json /tmp/repeatability.json
```

## Inputs and results

Set `--training` to an earlier RANGE and SATVIS2 capture from the same
stationary site. The live or replay input is the comparison pass. Use
`--cell-degrees` and `--minimum-cell-samples` to control the sky bins.

## Understanding the result

Keep the antenna and surroundings comparable between captures. A validation
capture must be at least 23 hours after the training capture starts, so that
it comes from a later repeat pass rather than the same day. GPS sky tracks
repeat after approximately one sidereal day (86,164 s nominal, with measured
per-satellite lags around 86,155 s, i.e. 236-245 s less than a solar day).
The sky-cell comparison does not apply a fixed time shift: it matches the same
satellite and signal in the same azimuth/elevation cell, and the reported
improvement is measured on held-out epochs.

## References

- Axelrad, Larson & Jones (2005), *Use of the Correct Satellite Repeat Period to
  Characterize and Reduce Site-Specific Multipath Errors*, ION GNSS.
- Larson, Bilich & Axelrad (2007), *Improving the precision of high-rate GPS*,
  JGR 112(B05422) (repeat period about 236 s shorter than 24 h).
- Choi et al. (2004), *Modified sidereal filtering*, GRL 31(L22608)
  (satellite-specific repeat lags).
