# Dual-antenna spoofing checks

Cross-check heading, visibility and spoof indicators.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.spoof_dual_antenna --port /dev/ttyUSB0 --baud 921600 \
    --duration 10 --record /tmp/spoof-checks.bin --json spoof.json
```

Replay a combined capture with heading, baseline and SPOOFINFO records:

```bash
python -m examples.spoof_dual_antenna \
    --replay /tmp/spoof-checks.bin
```

SPOOFINFO results include anomaly and signal masks and the satellite numbers
reported for each constellation. The sky comparison uses successive receiver
snapshots, so it is not a comparison between separate antenna feeds.

Live collection streams the required logs together. The ENU and ECEF baselines
must be computed, and their epochs and the primary-origin position must match
within `--position-tolerance` (default one second). The origin remains physical
ANT1 when baseline roles are swapped. Sky comparison needs two snapshots.

The individual BSLNENUHD fixture exercises baseline decoding only. Missing
heading, sky comparison or SPOOFINFO evidence produces `incomplete_checks` and exit code 1,
while retaining any available alarms. Exit code 0 means the required checks
were available; inspect `alarms` separately. These consistency checks cannot
establish that the received signals are authentic.

## References

- Kaplan & Hegarty (2017).
- Unicore UM982 manual.
