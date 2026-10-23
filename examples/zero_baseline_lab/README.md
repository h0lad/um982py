# Zero-baseline noise

Measures double-difference noise between two receivers on a zero baseline.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

Replay a capture:

```bash
python -m examples.zero_baseline_lab --replay captures/receiver-a.bin \
    --reference captures/receiver-b.bin --reference-prn 27 --json noise.json
```

## Inputs and results

`--replay` and `--reference` are captures from two receivers observing the same
zero-baseline setup. `--reference-prn` selects a common continuously locked GPS
satellite, while `--join-tolerance` limits the epoch mismatch in seconds.

## Understanding the result

A zero-baseline setup provides two receivers with the same antenna signal,
typically through a suitable splitter. The example compares time-aligned
observations using a common, continuously tracked reference satellite to study
relative noise in that setup without isolating every measurement error.

## References

Prochniewicz et al. (2021), zero-baseline noise.
