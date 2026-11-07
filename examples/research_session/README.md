# Research session recorder

Capture OBSVM/OBSVH, GPS, Galileo, GLONASS and BeiDou ephemerides, BESTNAVXYZ and RECTIME
to create observation RINEX, GPS navigation RINEX and an auditable manifest.
Live sessions also preserve the raw stream in `capture.bin` by default.

```bash
python -m examples.research_session --port /dev/ttyUSB0 --output-dir /tmp/session --duration 90
python -m examples.research_session --replay tests/fixtures/obsvm-example.txt --output-dir /tmp/replay-session
```

The supplied OBSVM sample produces `primary.obs` and `manifest.json`. To export
`gps.nav` as well, replay a session containing both observations and GPSEPH.
To export other captured constellations, replay `capture.bin` with
[`rinex_navigation`](../rinex_navigation/README.md) after verifying the
required signal-source and time-scale settings.

Choose an empty destination directory. When available, supply surveyed
coordinates and antenna information through `--metadata` and
`--secondary-metadata`. Both accept the JSON fields documented for
`RinexMetadata`. The manifest records the supplied antenna details and marks
the receiver configuration as unknown. This recorder exports GPS navigation;
the separate navigation exporter handles the other captured constellations.
A replay without observations still writes the manifest but returns a
nonzero status. Before scientific analysis, independently validate the RINEX
files and station metadata.

The versioned provenance section records the library version, hashes supplied
metadata files, and leaves unknown receiver identity, frame, coordinate epoch and
time scale explicit. Live observation quality checks use the requested interval
to identify gaps; replay does not assume that interval describes the recording.

## Compare base and rover observations

When the receiver is already receiving a correction stream on another input,
record the decoded base observations and primary-rover observations together:

```bash
python -m examples.research_session.base_rover --port /dev/ttyUSB0 --baud 921600 \
    --duration 60 --record /tmp/base-rover.bin --json /tmp/base-rover.json
python -m examples.research_session.base_rover --replay /tmp/base-rover.bin \
    --join-tolerance 0.1 --json /tmp/base-rover-replay.json
```

The example does not connect to a caster. Supply corrections through a separate
receiver input and retain their source and station metadata independently.
`OBSVBASE` is subscribed with `ONCHANGED`. The report pairs epochs and native
signal identifiers without interpolation or reuse. The default tolerance is zero;
`--join-tolerance` sets a maximum difference in seconds. Duplicate or ambiguous
matches are rejected, and unmatched epoch and signal counts remain visible.

The report retains raw pseudoranges, carrier phases, lock times and tracking
flags. Check signal identity, validity flags, time alignment and phase convention
before processing them. The example does not calculate double differences or
establish that the receiver used the corrections in its position solution.

## References

Unicore N4 R1.15 OBSVM, OBSVH and ephemeris logs; IGS/RTCM RINEX 3.05.

## Independent position comparison

To match independently prepared ECEF positions without interpolation, supply
CSV files with `gps_seconds,x_m,y_m,z_m` and an independently established frame:

```bash
python -m examples.research_session.compare_reference --observed rover.csv \
    --reference reference.csv --reference-frame ITRF2020 --output /tmp/comparison.json
```

The report preserves unmatched epochs and hashes both inputs. `--same-point`
records the user's assertion that both positions refer to the same point, but the
program does not verify reference frames, coordinate epochs or antenna points.
