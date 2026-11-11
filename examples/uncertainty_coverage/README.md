# Reported uncertainty calibration

Compare receiver-reported per-axis standard deviations with errors at an
independently known point.

## Run

From the repository root, run the **synthetic demonstration**:

```bash
python -m examples.uncertainty_coverage --input examples/uncertainty_coverage/sample.csv
```

Use your CSV with `--input` and `--json result.json` to save the report.

## Input

Each row contains east, north and up errors and the corresponding positive
receiver-reported standard deviations, in metres. Compute errors against a
surveyed point using the same coordinate frame and epoch. `--multiplier` sets
the threshold in sigma units (default 1).

## Explanation and interpretation

The report gives counts and fractions within the chosen per-axis threshold,
along with mean signed error and RMS error. It describes marginal per-axis
coverage rather than a three-dimensional confidence region and assumes no
probability distribution.

Use an independent reference survey and repeated observations under documented
conditions. Samples are often correlated over time, so do not count each row as
an independent observation. The report gives no confidence interval.

## References

- [NIST: Measurement uncertainty](https://www.nist.gov/pml/nist-technical-note-1297).
- [Library examples guide](../README.md).
