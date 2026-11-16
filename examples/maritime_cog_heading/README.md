# Maritime COG and heading

Compare the course over ground (COG) derived from single-antenna position
successions with the true heading reported by a dual-antenna UM982 baseline.

## Background

Vessel navigation often needs both heading and COG.  Heading shows where the
vessel points; COG shows where it actually moves.  The difference is caused by
current, leeway and timing latency.  This example matches the marine validation
approach in

> Aykut, N. O. (2026). Experimental Assessment of Course over Ground and Heading
> Determination for Marine Vessels Using Single- and Dual-Antenna GNSS
> Positioning Solutions. *Applied Sciences*, 16(20), 10228.
> doi:10.3390/app162010228

## Method

`BESTNAV` positions are sampled at the requested interval.  COG is computed from
each pair of consecutive positions using the great-circle bearing.  For the
same epochs `UNIHEADING` provides the dual-antenna true heading.  The report
calculates `heading - COG`, which is only meaningful when the vessel is moving
fast enough; epochs below `--min-speed` are kept but report `cog_deg = null`.

## Run

```bash
python -m examples.maritime_cog_heading \
    --port /dev/ttyUSB0 --baud 921600 \
    --duration 120 --interval 1 --min-speed 0.5
```

Use `--swap-antennas` if the baseline direction is reversed compared with the
vessel bow-stern axis.

## Output

For every matched epoch:

- `speed_ms` – receiver-reported horizontal speed
- `cog_deg` – finite-difference course over ground
- `heading_deg` – dual-antenna true heading
- `heading_minus_cog_deg` – signed difference, wrapped to -180..180

A statistics block reports mean, RMS, min and max of the signed differences.

## Limitations

- COG from position differences is noisy at low speed and during turns.
- Heading and COG are measured at slightly different times; interpolation or
  synchronisation would reduce latency-induced differences.
- Current, leeway and vessel yaw rate are confounded with GNSS heading error.
