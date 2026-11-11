# Unattended station recorder

Capture numbered research sessions with raw data, segment manifests and an
append-only JSONL journal. The recorder checks free disk space, prevents
concurrent use of the directory and never overwrites earlier segments.

```bash
python -m examples.unattended_station --port /dev/ttyUSB0 --directory /data/station --segments 0
python -m examples.unattended_station --replay tests/fixtures/obsvm-example.txt --directory /tmp/station-replay
```

Replay requires OBSVM or OBSVH observations. The default is one 15-minute
segment. `--segments 0` runs until interrupted.

Failed segments remain on disk. Set `--retry-seconds` to retry live capture.
An interruption can leave an unmatched start entry in the journal. Directory
locking requires POSIX.

For live sessions, the journal records firmware and configuration snapshots
before and after each segment. Failed queries do not stop capture. Changes
between snapshots may go undetected, and replay cannot recover them. Host
timestamps are not an independent time reference.

## References

- Unicore N4 R1.15 OBSVM/OBSVH.
- IGS/RTCM RINEX 3.05.

## Review station health

After a recording, run the report with an output path outside the station tree:

```bash
python -m examples.unattended_station.health_report --directory /data/station \
    --date 2026-01-01 --output /tmp/station-health.json \
    --markdown /tmp/station-health.md
```

The report lists incomplete and failed segments, low-disk events, log counts,
host-time intervals and configuration changes. It checks available hashes for
raw captures and exports. For missing files, `exists` is false and the hash
match is unknown.

Host-time intervals do not measure observation gaps. Omit `--date` to include
the whole journal. Otherwise, segments are selected by their host UTC start
date. Replay segments reference external input and have no local raw-capture
check.
