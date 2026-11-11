# Zero-baseline noise

Measure double-difference noise between two receivers on a zero baseline.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Replay a capture:

```bash
python -m examples.zero_baseline_lab --replay captures/receiver-a.bin \
    --reference captures/receiver-b.bin --reference-prn 27 --json noise.json
```

## Inputs and results

`--replay` and `--reference` are captures from two receivers observing the same
zero-baseline setup. `--reference-prn` selects a common continuously locked GPS
satellite. Noise estimation requires exactly matching GPS epochs, so
`--join-tolerance` must remain zero. Asynchronous observations cannot be
treated as simultaneous without correcting their time-dependent range changes.

## Understanding the result

A zero-baseline setup feeds the same antenna signal to both receivers, typically
through a splitter.

## References

Prochniewicz et al. (2021), zero-baseline noise.
