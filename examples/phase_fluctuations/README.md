# Low-rate carrier phase fluctuations

Measure linearly detrended phase variability on selected continuous carrier arcs.

## Run

From the repository root, run the **synthetic demonstration**:

```bash
python -m examples.phase_fluctuations --input examples/phase_fluctuations/sample.csv
```

Use your CSV with `--input` and `--json result.json` to save the report.

## Input

Each row has an `arc` identifier, time in seconds and range-increasing `phase_m`
in metres. Time must increase within each arc. Split arcs at every cycle slip,
loss of lock, signal change and gap. `--max-gap-s` rejects gaps above the
selected limit.

## Explanation and interpretation

For each arc, the example removes its least-squares straight line and reports
residual RMS, fitted slope, duration and maximum gap. The statistic depends on
arc duration, detrending and sample rate, so it is not automatically a phase
scintillation index.

Checking for gaps cannot identify an unmarked slip. Low-rate observations cannot
resolve variations above their sampling bandwidth.

## References

- [Phase scintillation with conventional GNSS receivers at 1 Hz](https://link.springer.com/article/10.1007/s00190-019-01297-z).
- [Library examples guide](../README.md).
