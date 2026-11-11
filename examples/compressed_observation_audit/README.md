# Compressed observation audit

Compare reconstructed RANGECMP observations with full RANGE observations at
shared epochs, and report the ratio of their wire sizes.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

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
Replay requires a capture with both binary logs. The report pairs epochs by
arrival order and observations by tracking status.

For each epoch, the report gives the match count and largest pseudorange,
Doppler and carrier-phase residuals. It also gives totals for the capture and
the ratio of compressed to full wire size. Saturated C/N0 entries count
separately because the compressed index clips both ends of its range.

## References

Unicore N4 R1.4 interface guide, OBSVMCMP compressed format.
