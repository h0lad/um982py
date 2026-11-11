# Three-frequency cycle-slip observability

Enumerate ideal responses to known injected integer cycle slips on three signals.

## Run

From the repository root, run the **synthetic demonstration**:

```bash
python -m examples.multifrequency_slips --input examples/multifrequency_slips/sample.csv
```

Use your CSV with `--input` and `--json result.json` to save the report.

## Input

Each row supplies three distinct carrier frequencies in Hz. For each signal,
`--max-cycles N` tests slip values from −N to +N cycles, excluding the all-zero
combination. `--gf-threshold-m` and `--closure-threshold-m` set experimental
thresholds in metres.

## Explanation and interpretation

For each candidate slip, the example converts cycles to distance using the
wavelength. It calculates two ideal responses. The first is the phase difference
between frequencies 1 and 2. The second is a three-frequency closure that
removes geometry and first-order ionosphere. The report shows whether either
response crosses its threshold.

These ideal responses show which injected slips the combinations can
distinguish. The example does not detect slips in receiver data.

Verify signs and wavelength conventions against labelled injected phase jumps.
The enumeration does not model noise, ionospheric evolution, Doppler, real arcs,
false alarms or half-cycle slips, and it does not measure a detection rate.

## References

- [Cai et al.: Enhanced cycle slip detection for dual-frequency BeiDou observations](https://hdl.handle.net/1721.1/121403).
- [Library examples guide](../README.md).
