# Journey motion: sea, aviation and outdoor sport

Capture or replay BESTNAVXYZ positions with DOPPVEL Doppler velocity reports
to inspect ground speed, true course, vertical speed, ellipsoidal height and
solution type. The report integrates horizontal speed over recorded intervals
and estimates moving time. Profiles for sailing, flying and mountain biking use
the same measurement model. Adjust the thresholds to suit your data.

```bash
python -m examples.journey_track --profile marine --port /dev/ttyUSB0 --duration 300 --dual-heading --record /tmp/passage.bin --json /tmp/passage.json
python -m examples.journey_track --profile aviation --replay /tmp/passage.bin --json /tmp/flight.json
python -m examples.journey_track --profile sport --replay /tmp/passage.bin --moving-threshold-mps 1 --json /tmp/sport.json
```

To write a GPX track directly from GGA fixes:

```python
from um982py import Receiver
from um982py.track import TrackWriter

with Receiver.connect("/dev/ttyUSB0", 921600) as receiver:
    with TrackWriter("walk.gpx", format="gpx", reference_frame="WGS84") as track:
        for fix in receiver.poll_positions(interval=1):
            if fix.valid:
                track.write(fix)
```

GPX uses mean-sea-level height, and GeoJSON uses ellipsoidal height. GGA has no
date, so pass a verified timezone-aware `timestamp` to `write()` when needed.
The writer requires a new file. Start a new track after a data gap.

`--dual-heading` requests BSLNENUHD. Each position pairs with a computed baseline
within `--heading-tolerance-s`, and the report records the time offset. This
heading follows the antenna baseline. Establish the mounting orientation before
using it as a vessel or aircraft heading. Course over ground can differ from
that heading. If the installed antenna roles are reversed, set `--swap-antennas`.

Ground speed, course over ground and vertical speed come from computed DOPPVEL
Doppler solutions. Each position takes the nearest valid DOPPVEL epoch within
`--doppler-tolerance-s` and reports the epoch offset, receiver latency, age and
reported speed standard deviations. No interpolation or latency correction is
applied. Captures with no DOPPVEL records at all fall back to Doppler-typed
ECEF velocity in BESTNAVXYZ; the sample's `velocity_source` shows which
measurement was used. Below `--course-threshold-mps`, the report omits
course. Distance uses trapezoidal integration of speed over the position
intervals. An interval counts as moving when its mean speed meets
`--moving-threshold-mps`. Invalid solutions and intervals longer than
`--max-gap-s` do not contribute.

The report shows the time covered by valid intervals. Noise can inflate the
distance, and peak speed is unfiltered. DOPPVEL shares observations with the
position solution, so its agreement with the receiver velocity is not an
independent accuracy check. It is a computed Doppler solution, not a raw
Doppler measurement.

Add `--waypoint LAT LON` to report approximate great-circle distance and initial
true bearing to a destination, and the horizontal velocity component towards it.
Closing speed uses Doppler course and is omitted when course is suppressed.
Distances use a mean-radius sphere rather than an ellipsoidal model. Closing
speed can be negative, and the report does not predict arrival time.

GPS timestamps are GPS seconds, not UTC. Heights are above the WGS84 ellipsoid,
not mean sea level, barometric altitude, or terrain clearance. GNSS ground speed
is not airspeed or speed through water. The example is an experimental
post-capture analysis, not a certified navigation, collision avoidance, or
emergency system.

For a current rover position in an application, `rover.position(heading=True)`
returns an epoch-matched baseline heading when available. Call
`position.motion(heading_offset_deg=...)` for ground speed, course, vertical
speed and mounting-adjusted heading, or `motion.waypoint(latitude, longitude)`
for approximate bearing and closing speed. Velocity can have a different epoch
from the position, and `motion.velocity_epoch_gps_seconds` incorporates the
receiver-reported latency when both it and the GPS epoch are available.

## References

- Unicore N4 R1.15 BESTNAVXYZ position and velocity fields.
- Unicore N4 DOPPVEL receiver Doppler velocity fields.
- BSLNENUHD receiver baseline extension.
