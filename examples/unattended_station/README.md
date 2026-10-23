# Unattended station recorder

Capture numbered research sessions to an existing or new directory, preserving
raw data, per-segment manifests and an append-only JSONL journal. The program
checks free disk space before each segment and refuses concurrent use of its
output directory. Restarting creates a new segment without overwriting earlier
files, including incomplete segments.

```bash
python -m examples.unattended_station --port /dev/ttyUSB0 --directory /data/station --segments 0
python -m examples.unattended_station --replay tests/fixtures/obsvm-example.txt --directory /tmp/station-replay
```

Replay requires OBSVM or OBSVH observations. A RANGE-only capture cannot
produce the session observation file. By default the recorder captures one
15-minute segment. Set `--segments 0` to run until interrupted.

A failed segment remains on disk for diagnosis. The recorder stops unless
`--retry-seconds` sets a delay for retrying a live capture. The journal records
starts and completions separately, so an interruption can leave an unmatched
start entry. The directory lock requires a POSIX system.

For live sessions, the journal records firmware details and selected receiver
configuration fields before and after each segment, plus a digest of the sorted
configuration entries. A failed query is recorded but does not stop capture.
The snapshots cannot establish whether settings changed between queries, and
replay cannot recover them. Host timestamps are not an independent time
reference. Review the manifest, disk space, antenna metadata and power before
using a recording.

## References

Unicore N4 R1.15 OBSVM/OBSVH; IGS/RTCM RINEX 3.05.

## Review station health

After a recording, run the report with an output path outside the station tree:

```bash
python -m examples.unattended_station.health_report --directory /data/station \
    --date 2026-01-01 --output /tmp/station-health.json \
    --markdown /tmp/station-health.md
```

The report lists incomplete and failed segments, disk-low events, captured log
counts, inter-segment host-time intervals and configuration snapshot changes.
It checks raw capture and exported artifact hashes when the manifest supplies
them. A missing artifact has `exists: false` and an unknown hash match. Host-time
intervals are not observation-gap measurements, and matching snapshots do not
exclude configuration changes between queries. Omit `--date` to include the
whole journal. A dated report assigns a segment to its host UTC start date.
Replay manifests refer to an external input, so the report does not check a
local raw capture for those segments.
