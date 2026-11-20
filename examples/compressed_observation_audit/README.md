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
Use `--antenna 2` for RANGEHB and RANGECMPHB on receivers that provide them.
Replay requires a capture with both binary logs. The report pairs observations
by receiver epoch, satellite PRN and native tracking status.

For each epoch, the report gives the match count and largest pseudorange,
Doppler and carrier-phase residuals. It also gives totals for the capture and
the ratio of compressed to full wire size. Saturated C/N0 entries count
separately because the compressed index clips both ends of its range.

## RANGECMP2 on the UM982

Use `--rangecmp2` to compare binary RANGECMP2 against simultaneous full
observations. The report measures the GPS L1 C/A range residual, checks for
128 m wraps and records when the L1 carrier-phase field reaches its maximum.
With a locked L2 phase below that maximum, the experiment also selects the
128 m fold nearest the L2 phase distance and measures the remaining error.
The report compares this phase distance with the simultaneous full L2 phase
when available.

```bash
python -m examples.compressed_observation_audit --port /dev/ttyUSB0 \
    --baud 921600 --duration 15 --interval 1 --rangecmp2 --antenna 2 \
    --record secondary.bin --json secondary.json
python -m examples.compressed_observation_audit --replay secondary.bin \
    --rangecmp2 --antenna 2 --json secondary-replay.json
```

In a 15-epoch capture, 89 of 135 primary and 75 of 135 secondary GPS L1
pseudoranges wrapped. All had the maximum L1 phase offset. The L2 phase
anchor selected the correct fold to within one encoded step (7.8125 mm)
in all 45 primary and 30 secondary cases where the phase passed the checks.
The reconstructed L2 phase distance agreed within 0.63 mm in those cases.
The fold is an experimental estimate and depends on the L2 phase being
within 64 m of the true L1 pseudorange. Use the full `RANGE` family for
absolute observations and when comparing receiver signal configurations.
[OEM7 RANGECMP2 wire layout](https://docs.novatel.com/OEM7/Content/Logs/RANGECMP2.htm)

Python callers can inspect the native blocks with
`um982py.experimental.rangecmp2_read` and `decode_rangecmp2`.

## References

Unicore N4 R1.4 interface guide, OBSVMCMP compressed format.
