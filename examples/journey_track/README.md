# Journey motion: sea, aviation and outdoor sport

Capture or replay BESTNAVXYZ solutions to inspect ground speed, true course,
vertical speed, ellipsoidal height and solution type. The report integrates
horizontal speed over recorded intervals and estimates moving time. Profiles
for sailing, flying and mountain biking use the same measurement model. Adjust
the thresholds to suit your data.

```bash
python -m examples.journey_track --profile marine --port /dev/ttyUSB0 --duration 300 --dual-heading --record /tmp/passage.bin --json /tmp/passage.json
python -m examples.journey_track --profile aviation --replay /tmp/passage.bin --json /tmp/flight.json
python -m examples.journey_track --profile sport --replay /tmp/passage.bin --moving-threshold-mps 1 --json /tmp/sport.json
```

To write a GPX track directly from GGA fixes:

```python
from um982py import Receiver, TrackWriter

with Receiver.connect("/dev/ttyUSB0", 921600) as receiver:
    with TrackWriter("walk.gpx", format="gpx", reference_frame="WGS84") as track:
        for fix in receiver.poll_positions(interval=1):
            if fix.valid:
                track.write(fix)
```

GPX uses mean-sea-level height; GeoJSON uses ellipsoidal height. GGA has no
date, so pass a verified timezone-aware `timestamp` to `write()` when needed.
The writer requires a new file. Start a new track after a data gap.

`--dual-heading` requests BSLNENUHD. Each position pairs with a computed baseline
within `--heading-tolerance-s`, and the report records the time offset. This
heading follows the antenna baseline. Establish the mounting orientation before
using it as a vessel or aircraft heading. Course over ground can differ from
that heading. If the installed antenna roles are reversed, set `--swap-antennas`.

Ground speed comes from the receiver's computed ECEF velocity, rotated into the
local WGS84 ENU frame. Below `--course-threshold-mps`, the report omits course.
Distance uses trapezoidal integration of speed. An interval counts as moving
when its mean speed meets `--moving-threshold-mps`. Invalid solutions and
intervals longer than `--max-gap-s` do not contribute.

The report shows the time covered by valid intervals. Noise can inflate the
distance, and peak speed is unfiltered. The report records velocity latency
without correcting for it.

Add `--waypoint LAT LON` to report approximate great-circle distance and initial
true bearing to a destination, and the horizontal velocity component towards it.
Distances use a mean-radius sphere rather than an ellipsoidal model. Closing
speed can be negative, and the report does not predict arrival time.

GPS timestamps are GPS seconds, not UTC. Heights are above the WGS84 ellipsoid,
not mean sea level, barometric altitude, or terrain clearance. GNSS ground speed
is not airspeed or speed through water. The example is an experimental
post-capture analysis, not a certified navigation, collision avoidance, or
emergency system.

## References

- Unicore N4 R1.15 BESTNAVXYZ position and velocity fields.
- BSLNENUHD receiver baseline extension.
