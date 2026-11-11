# User equivalent range error

Estimate user range error from position uncertainty and DOP.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.uere_budget --port /dev/ttyUSB0 --baud 921600 \
    --json uere.json
```

Replay a capture:

```bash
python -m examples.uere_budget --replay /tmp/uere.bin
```

## Inputs and results

The calculation pairs computed SINGLE PSRPOS fixes with PSRDOP at the same
epoch. The logs do not establish whether both used the same satellites. Check
this independently before passing `--assume-matched-geometry`. The inversion
also assumes unweighted geometry and equal, independent range errors. Without
the flag, the example reports insufficient data.

## Understanding the result

The reported pseudorange sigma is a receiver measurement diagnostic, not total
UERE.

## References

Kaplan & Hegarty (2017), Understanding GPS/GNSS.
