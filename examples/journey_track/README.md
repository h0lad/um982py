# Journey motion: sea, aviation and outdoor sport

Capture or replay BESTNAVXYZ solutions and inspect ground speed, true course,
vertical speed, ellipsoidal height, and receiver solution types. The report also
integrates horizontal speed over covered intervals and estimates moving time.
Use it to review, for example, a sailing passage, flight test or mountain-bike
descent. The profiles label the activity but use the same measurement model.
Adjust the thresholds to suit your data and activity.

```bash
python -m examples.journey_track --profile marine --port /dev/ttyUSB0 --duration 300 --dual-heading --record /tmp/passage.bin --json /tmp/passage.json
python -m examples.journey_track --profile aviation --replay /tmp/passage.bin --json /tmp/flight.json
python -m examples.journey_track --profile sport --replay /tmp/passage.bin --moving-threshold-mps 1 --json /tmp/sport.json
```

`--dual-heading` requests BSLNENUHD and pairs a computed baseline with each
position within `--heading-tolerance-s`. Its direction describes the antenna
baseline, so establish the mounting orientation before interpreting it as a
vessel or aircraft heading. Course over ground can differ from that direction.
The report retains the pairing offset. Set `--swap-antennas` if the installed
antenna roles are reversed.

Ground speed is the horizontal component of the receiver's computed ECEF
velocity. Course is suppressed below `--course-threshold-mps`. The report
integrates speed with a trapezoidal rule and counts time as moving when the
interval's mean speed meets `--moving-threshold-mps`. Invalid solutions and
intervals longer than `--max-gap-s` are excluded. Check the reported covered
time to see how much data contributed. Noise can inflate distance, and peak
speed is an unfiltered sample. Velocity latency is recorded but not corrected.

Add `--waypoint LAT LON` to report approximate great-circle distance and initial
true bearing to a destination, and the horizontal velocity component towards it.
These distances use a mean-radius sphere and are not a precise ellipsoidal route.
Closing speed can be negative, and the report does not predict arrival time.

GPS timestamps are GPS seconds, not UTC. Heights are above the WGS84 ellipsoid,
not mean sea level, barometric altitude, or terrain clearance. GNSS ground speed
is not airspeed or speed through water. The example is an experimental
post-capture analysis, not a certified navigation, collision avoidance, or
emergency system. Check the equipment, timestamps, antenna mounting, and local
operating requirements before using it in the field.

## References

Unicore N4 R1.15 BESTNAVXYZ position and velocity fields; BSLNENUHD receiver
baseline extension. ECEF velocities are rotated into the local WGS84 ENU frame.
