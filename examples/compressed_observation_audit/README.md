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

In the tested UM982 capture, the `RANGECMP2B` and `RANGECMP2HB` payloads follow
the OEM7 satellite and signal block framing. The encoder keeps only the low
14 bits of the pseudorange difference at 1/128 m resolution, so a difference
outside the 128 m window wraps. [OEM7 RANGECMP2 wire layout](https://docs.novatel.com/OEM7/Content/Logs/RANGECMP2.htm)

Across 11 matched epochs per antenna, 78 of 110 primary and 77 of 110
secondary GPS L1 pseudoranges differed from their simultaneous `RANGE` or
`RANGEH` values by multiples of 128 m. The largest discrepancy was about
5,387 km. Every affected observation also had the maximum encoded
carrier-phase difference. Use the full `RANGE` family or the audited
`RANGECMP` family for UM982 observations.

## References

Unicore N4 R1.4 interface guide, OBSVMCMP compressed format.
