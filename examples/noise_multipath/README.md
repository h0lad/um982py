# Receiver noise and repeat-track study

Compare shared-antenna and separate-antenna differences with held-out
repeat-track measurements.

## Run

From the repository root, run the **synthetic demonstration**:

```bash
python -m examples.noise_multipath --input examples/noise_multipath/sample.csv
```

Use your CSV with `--input` and `--json result.json` to save the report.

## Input

`kind` is `shared`, `separate`, or `repeat`. The first two use `difference_m`.
For `repeat`, provide paired `day1_m` and `day2_m` values from the same signal
and matched sky cell on independent days. Use the same differencing convention
and units. Blank cells are allowed only where unused.

## Explanation and interpretation

The report gives unbiased sample variances, their signed difference and the
Pearson correlation of matched repeat-track values. Negative variance
differences remain in the output. They can occur with shared errors,
reference-satellite covariance, changing conditions or temporal correlation.
The difference cannot uniquely separate noise from multipath.

Use a suitable splitter and two receivers for the shared-antenna experiment.
Repeat with separate antennas, then use independent days for the held-out
comparison. Check the matched epochs and signal identities independently.

## References

- [Prochniewicz et al. (2021): Empirical stochastic model of multi-GNSS measurements](https://doi.org/10.3390/s21134566).
- [Library examples guide](../README.md).
