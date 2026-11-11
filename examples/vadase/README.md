# VADASE motion estimates

Estimate displacement and velocity from time-differenced carrier phase.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.vadase --port /dev/ttyUSB0 --baud 921600 --duration 60 \
    --interval 0.2 --record captures/motion.bin --json motion.json
```

Replay the supplied capture:

```bash
python -m examples.vadase --replay tests/fixtures/specialist/rtklib-motion.bin \
    --truth-velocity 0.03 -0.02 0.01 --json /tmp/motion.json
```

## Inputs and results

`--observer X Y Z` gives an approximate ECEF receiver position in metres.
`--truth-velocity VX VY VZ` supplies an independent constant ECEF velocity in
metres per second for comparison. Continuous carrier-phase arcs are needed.

## Understanding the result

A cycle slip or gap can invalidate an arc.

## References

Colosimo, Crespi & Mazzoni (2011), VADASE.

## Replay a displacement event

Generate both motion reports from the same capture, then align their epochs:

```bash
python -m examples.doppler_velocity --replay event.bin --json /tmp/doppler.json
python -m examples.vadase --replay event.bin --json /tmp/tdcp.json
python -m examples.vadase.event_replay --doppler /tmp/doppler.json \
    --tdcp /tmp/tdcp.json --reference-frame ITRF2020 \
    --reference independent-velocity.csv --output /tmp/event.json
```

The optional independent CSV uses `gps_seconds,vx_mps,vy_mps,vz_mps` in the
same ECEF frame, with velocities in metres per second. Epochs are paired only
within `--match-window-s`. Unmatched phase epochs and solver rejections remain
in the report. Doppler velocity is an epoch estimate, while TDCP velocity is an
average between its reported start and end epochs. The comparison does not
align those time spans or integrate through gaps. Establish sensor timing,
sample rate, frame and antenna point independently before interpreting a real
event. This analysis is not an earthquake warning system.
