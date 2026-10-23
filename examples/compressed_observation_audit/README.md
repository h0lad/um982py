# Compressed observation audit

Compares RANGECMP reconstructions with full RANGE observations over shared
epochs and reports the wire-size ratio.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

Connect to a receiver:

```bash
python -m examples.compressed_observation_audit --port /dev/ttyUSB0 \
    --baud 921600 --duration 10 --interval 1 --json audit.json
```

Replay a capture:

```bash
python -m examples.compressed_observation_audit --replay wire.bin \
    --json audit.json
```

## Inputs and results

Live capture subscribes to RANGEB and RANGECMPB at `--interval` for
`--duration` seconds and restores the previous subscriptions afterward.
Replay requires wire bytes holding both binary logs. Epochs pair by arrival
order; observations pair by tracking status.

The report lists per-epoch match counts with worst-case pseudorange, Doppler
and carrier-phase residuals, plus whole-capture totals and the compressed to
full wire-size ratio. Saturated C/N0 entries count separately because the
compressed index clips both ends of its range.

## References

Unicore N4 R1.4 interface guide, OBSVMCMP compressed format.
