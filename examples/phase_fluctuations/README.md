# Low-rate carrier phase fluctuations

Measure linearly detrended phase variability on explicitly selected continuous carrier arcs.

## Run

From the `lib/um982py` project directory, run the **synthetic demonstration**:

```bash
python -m examples.phase_fluctuations --input examples/phase_fluctuations/sample.csv
```

Supply your own carrier-phase arcs with `--input` and add `--json result.json`
to save the report. No receiver connection is required.

## Input

Each row has an `arc` identifier, strictly increasing time in seconds within the arc, and range-increasing `phase_m` in metres. Split arcs at every cycle slip, loss of lock, signal change and gap. `--max-gap-s` rejects gaps above the selected limit.

The included arcs are synthetic and do not measure receiver performance.

## Explanation and interpretation

For each arc, the example removes its least-squares straight line and reports
residual RMS, fitted slope, duration and maximum gap. The statistic depends on
arc duration, detrending and sample rate, so it is not automatically a phase
scintillation index.

Compare the results with independently validated phase measurements and
controlled injected signals: a gap check cannot identify an unmarked slip, and
low-rate observations cannot resolve variations above their sampling bandwidth.

## References

- [Phase scintillation with conventional GNSS receivers at 1 Hz](https://link.springer.com/article/10.1007/s00190-019-01297-z).
- [Library examples guide](../README.md).
