# Ice motion from position epochs

Read a time-ordered CSV with `gps_seconds,x_m,y_m,z_m` and export ECEF and local
ENU displacement relative to the first epoch, along with two-epoch velocity.
A gap longer than `--max-gap-s` suppresses the corresponding velocity estimate.
Alternatively, `--replay` reads computed BESTNAVXYZ records from a receiver
capture. A record without a computed solution, with non-finite coordinates or
at the undefined ECEF origin breaks the velocity series. The output records
its epoch and rejection reason. Each position reports why velocity is unavailable when it cannot be
calculated. A CSV has no solution-status field, so its rows are treated as
user-provided valid positions.

```bash
python -m examples.ice_motion --input positions.csv --reference-frame ITRF2020 --output /tmp/motion.json
```

Supply independently established positions in a common reference frame. The
first position defines the local origin and is not treated as surveyed truth.
The output contains no covariance or independently verified accuracy. It does
not interpolate gaps, correct antenna motion or validate the frame and
coordinate epoch. The local ENU orientation uses the WGS84 ellipsoid at the
first position.

## References

Unicore N4 R1.15 BESTNAVXYZ; standard ECEF-to-ENU rotation.
