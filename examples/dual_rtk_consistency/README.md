# Dual-RTK consistency check

A UM982 with dual-RTK output provides position solutions for the
master (ANT1) and slave (ANT2) antennas.  This example takes those two
positions, forms a baseline vector, and compares the resulting heading and pitch
with the receiver's own `UNIHEADING` solution.

## Background

The idea matches the moving-baseline validation used in autonomous-vehicle work:

> Han, J., Park, C., Jang, Y. Y., et al. (2022). Development of a Moving
> Baseline RTK/Motion Sensor-Integrated Positioning-Based Autonomous Driving
> Algorithm for a Speed Sprayer. *Sensors*, 22(24), 9881.
> doi:10.3390/s22249881

When both antennas maintain RTK fixed solutions, the master-slave position
difference is a redundant attitude estimate.  Epochs where only one antenna is
fixed are flagged explicitly because the cross-check is then unreliable.

## Run

```bash
python -m examples.dual_rtk_consistency \
    --port /dev/ttyUSB0 --baud 921600 \
    --duration 30 --interval 1
```

Make sure the receiver is configured to output `BESTNAV`, `BESTNAVH` and
`UNIHEADING`.  The example requests them temporarily if they are not already on.

## Output

For every matched epoch the report contains:

- `master_ecef` / `slave_ecef` – ECEF positions of each antenna
- `diff_enu` – local ENU baseline from master to slave
- `diff_length_m` – length of the position-derived baseline
- `computed_heading_deg` / `computed_pitch_deg` – heading and pitch from the
  position difference
- `receiver_heading_deg` / `receiver_pitch_deg` – values reported in
  `UNIHEADING`
- `heading_residual_deg` / `pitch_residual_deg` – difference between the two
- `master_rtk_fixed` / `slave_rtk_fixed` – whether each antenna reports an
  RTK-fixed solution

A statistics block summarises the residual mean/RMS and the distribution of
RTK fix states across the matched epochs.

## Limitations

- The position-derived baseline is noisier than a carrier-phase baseline and
  depends on both antennas being RTK fixed.
- Antenna-specific multipath and antenna offsets are not modelled.
- The outputs may share measurements, corrections and receiver processing;
  agreement with `UNIHEADING` is not independent validation.
- Fixed status requires both a computed solution and a documented fixed type,
  for either ASCII or binary logs.
