# Research session recorder

Create observation RINEX, GPS navigation RINEX and a session manifest. The
recorder captures OBSVM/OBSVH, ephemerides for GPS, Galileo, GLONASS and BeiDou,
BESTNAVXYZ and RECTIME. Live sessions also save the raw stream to `capture.bin`
by default.

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
the receiver configuration as unknown.

A replay without observations still writes a manifest and returns a nonzero
status.

The manifest's versioned provenance section contains the library version and
hashes of supplied metadata files. Receiver identity, frame, coordinate epoch
and time scale stay marked as unknown when unavailable. Live quality checks
detect gaps against the requested interval. Replay does not assume that this
interval matches the recording.

## Compare base and rover observations

When the receiver is already receiving a correction stream on another input,
record the decoded base observations and primary-rover observations together:

```bash
python -m examples.research_session.base_rover --port /dev/ttyUSB0 --baud 921600 \
    --duration 60 --record /tmp/base-rover.bin --json /tmp/base-rover.json
python -m examples.research_session.base_rover --replay /tmp/base-rover.bin \
    --join-tolerance 0.1 --json /tmp/base-rover-replay.json
```

Supply corrections through a separate receiver input and keep their source and
station metadata. The example does not connect to a caster. It subscribes to
`OBSVBASE` with `ONCHANGED`.

The report pairs epochs and native signal identifiers without interpolation
or reuse. Epochs must match exactly by default. Use `--join-tolerance` to allow
a maximum time difference in seconds. The report rejects duplicate or ambiguous
matches and counts unmatched epochs and signals.

The report retains raw pseudoranges, carrier phases, lock times and tracking
flags. Check signal identity, validity flags, time alignment and phase convention
before processing them. The example does not calculate double differences or
establish that the receiver used the corrections in its position solution.

## References

- Unicore N4 R1.15 OBSVM, OBSVH and ephemeris logs.
- IGS/RTCM RINEX 3.05.

## Independent position comparison

To match independently prepared ECEF positions without interpolation, supply
CSV files with `gps_seconds,x_m,y_m,z_m` and an independently established frame:

```bash
python -m examples.research_session.compare_reference --observed rover.csv \
    --reference reference.csv --reference-frame ITRF2020 --output /tmp/comparison.json
```

The report preserves unmatched epochs and hashes both inputs. `--same-point`
records your assertion that the positions refer to the same physical point.
You must check the reference frames, coordinate epochs and antenna points.
