# Three-frequency cycle-slip observability

Enumerate ideal responses to known injected integer cycle slips on three signals.

## Run

From the `lib/um982py` project directory, run the **synthetic demonstration**:

```bash
python -m examples.multifrequency_slips --input examples/multifrequency_slips/sample.csv
```

Supply your own frequency combinations with `--input` and add
`--json result.json` to save the report. No receiver connection is required.

## Input

One row supplies three distinct carrier frequencies in Hz. `--max-cycles` enumerates nonzero signed slip triples from minus to plus that value. `--gf-threshold-m` and `--closure-threshold-m` set explicit experimental thresholds in metres.

The included frequencies are synthetic and do not establish detection performance.

## Explanation and interpretation

For each candidate slip, the example converts cycles to distance using the
wavelength and calculates two ideal responses: the phase difference between
frequencies 1 and 2, and a three-frequency closure that removes geometry and
first-order ionosphere. It reports whether either response crosses its threshold, but
the experiment studies observability rather than detecting slips in receiver data.

Verify signs and wavelength conventions against labelled injected phase jumps.
The enumeration does not model noise, ionospheric evolution, Doppler, real arcs,
false alarms or half-cycle slips, and it does not measure a detection rate.

## References

- [Cai et al.: Enhanced cycle slip detection for dual-frequency BeiDou observations](https://hdl.handle.net/1721.1/121403).
- [Library examples guide](../README.md).
