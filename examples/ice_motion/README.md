# Ice motion from position epochs

Read positions from a time-ordered CSV with `gps_seconds,x_m,y_m,z_m`, or use
`--replay` to read computed BESTNAVXYZ records from a receiver capture. The
output gives ECEF and local ENU displacement from the first epoch, and velocity
between epochs.

A gap longer than `--max-gap-s` suppresses the velocity estimate. Missing
solutions, non-finite coordinates and the undefined ECEF origin also break the
series. The output explains why epochs were rejected and velocity estimates
are missing. CSV rows have no solution status, so the program treats them as
valid positions.

```bash
python -m examples.ice_motion --input positions.csv --reference-frame ITRF2020 --output /tmp/motion.json
```

Supply independently established positions in a common reference frame. The
first position defines the local origin, with ENU orientation from the WGS84
ellipsoid at that point. The program does not survey or verify the reference.
The output has no covariance or correction for antenna motion, and does not
interpolate across gaps. The program does not validate the frame or coordinate
epoch.

## References

- Unicore N4 R1.15 BESTNAVXYZ.
- standard ECEF-to-ENU rotation.
