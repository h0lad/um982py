# Urban NLOS filter

Classify each tracked satellite as likely line-of-sight (LOS), unsure, or likely
non-line-of-sight (NLOS) using only receiver-reported elevation and C/N0.

## Background

Urban-canyon positioning degrades because reflected and diffracted signals are
tracked alongside direct signals.  Receiver-only indicators are weaker than
3-D city models or additional sensors, but they are available on every low-cost
module.  This example follows the classical indicators discussed in

> Groves, P. D., & Jiang, Z. (2013). Height Aiding, C/N0 Weighting and Consistency
> Checking for GNSS NLOS and Multipath Mitigation in Urban Areas. *The Journal of
> Navigation*, 66(6), 653-669. doi:10.1017/S0373463313000169

## Method

For each SATSINFO signal a score is computed from:

- elevation factor: lower elevation -> higher NLOS likelihood
- C/N0 factor: lower C/N0 -> higher NLOS likelihood

The combined score is then thresholded into three classes:

- LOS: score < `low_threshold`
- unsure: `low_threshold` <= score < `high_threshold`
- NLOS: score >= `high_threshold`

Default thresholds are 0.45 and 0.75 and can be tuned with command-line flags.

## Run

```bash
python -m examples.urban_nlos_filter \
    --port /dev/ttyUSB0 --baud 921600 \
    --duration 60 --interval 1
```

## Output

The JSON report contains per-epoch classifications and aggregate counts:

- `mean_score` – average uncalibrated heuristic score across the epoch
- `counts` / `fractions` – LOS, unsure and NLOS proportions
- per-signal `candidates` with PRN, elevation, azimuth, C/N0, score and label

## Independent evaluation

Supply `--labels-csv labels.csv` with columns `elevation_deg,cn0_db_hz,truth`,
where `truth` is `LOS` or `NLOS`. The report tabulates all three predicted classes,
including unsure, against the supplied labels. Use independently labelled,
held-out data, not the same data used to choose thresholds. This does not
calibrate probabilities or account for correlated samples.

## Limitations

- The score is not a probability. This is a heuristic, not a physical NLOS detector.  Low elevation and low C/N0
  can also be caused by foliage, interference, poor antenna placement or
  receiver saturation.
- The score does not use pseudorange residuals, sky-view geometry or 3-D maps,
  which would improve accuracy at the cost of extra data.
- Use the labels only as candidates for exclusion or down-weighting.
