# Reported uncertainty calibration

Compare receiver-reported per-axis standard deviations against errors at an independently known point.

## Run

From the `lib/um982py` project directory, run the **synthetic demonstration**:

```bash
python -m examples.uncertainty_coverage --input examples/uncertainty_coverage/sample.csv
```

Supply your own position errors and reported uncertainties with `--input` and
add `--json result.json` to save the report. No receiver connection is required.

## Input

Each row contains east, north and up errors and the corresponding positive receiver-reported standard deviations, in metres. Compute errors against a surveyed point in a consistent coordinate frame and epoch. `--multiplier` sets the threshold in sigma units (default 1).

The included errors and uncertainties are synthetic and do not assess a receiver.

## Explanation and interpretation

The report gives counts and fractions within the chosen per-axis threshold,
along with mean signed error and RMS error. It describes marginal per-axis
coverage rather than a three-dimensional confidence region and assumes no
probability distribution.

Use an independent reference survey and repeated observations under documented
conditions. Samples are commonly time-correlated, so the number of rows does not
represent an independent sample count, and the report does not provide a confidence
interval.

## References

- [NIST: Measurement uncertainty](https://www.nist.gov/pml/nist-technical-note-1297).
- [Library examples guide](../README.md).
