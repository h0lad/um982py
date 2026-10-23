# Receiver noise and repeat-track study

Compare shared-antenna and separate-antenna differences and held-out repeat-track measurements.

## Run

From the `lib/um982py` project directory, run the **synthetic demonstration**:

```bash
python -m examples.noise_multipath --input examples/noise_multipath/sample.csv
```

Supply your own paired differences with `--input` and add `--json result.json`
to save the report. No receiver connection is required.

## Input

`kind` is `shared`, `separate`, or `repeat`. The first two use `difference_m`, while `repeat` rows use paired `day1_m` and `day2_m` from the same signal and matched sky cell on independent days. Differences must use the same differencing convention and units. Blank cells are allowed only where unused.

The included differences are synthetic and do not characterize a receiver or site.

## Explanation and interpretation

The output reports unbiased sample variances, their signed difference and the
Pearson correlation of matched repeat-track values. It retains negative variance
differences, which can arise alongside shared errors, reference-satellite
covariance, changing conditions and temporal correlation, so the difference is not
a unique decomposition of noise and multipath.

Use a suitable splitter and two receivers for the shared-antenna experiment,
then repeat with separate antennas and independent held-out days, checking the
matched epochs and signal identities independently.

## References

- [Prochniewicz et al. (2021): Empirical stochastic model of multi-GNSS measurements](https://doi.org/10.3390/s21134566).
- [Library examples guide](../README.md).
