# GPS RINEX navigation export

Export the receiver's GPS broadcast ephemerides (`GPSEPH`) as a RINEX 3.05
navigation file. Use this alongside an observation file from
[`rinex_export`](../rinex_export/README.md).

## Run

After [installing the package](../README.md#running-the-examples), run the
commands from the repository root.

Collect ephemerides from a receiver:

```bash
python -m examples.rinex_navigation --port /dev/ttyUSB0 --baud 921600 \
    --duration 300 --interval 30 --output gps.nav --json gps-nav.json
```

Export the supplied recording without hardware:

```bash
python -m examples.rinex_navigation \
    --replay tests/fixtures/captures/GPSEPHA.bin \
    --output /tmp/replay-gps.nav --json /tmp/replay-gps-nav.json
```

## Inputs and results

The input must contain GPSEPH records. RANGE or OBSVM observations alone cannot
produce a navigation file. `--duration` and `--interval` control live capture;
`--frames` limits the number of captured or replayed records to 100 by default.

`--output` writes the navigation file. `--json` writes a report with the format,
number of exported messages and `unknown_fields`. Input, capture, navigation and
report paths must be distinct.

Only GPS navigation data is exported. The command preserves repeated messages;
the message count is not a count of distinct satellites. The supplied recording
demonstrates the export format.

## Understanding the result

The receiver does not expose every navigation field required by RINEX. L2
codes, the L2 P-data flag and fit interval remain blank. Transmission time uses
the RINEX unknown-time sentinel, because the receiver's `tow` field is not
independently established as the message transmission time. The report lists
these four fields rather than filling in assumed values.

For downstream processing, use ephemerides covering the same satellites and
times as the observation file, and inspect the receiving tool's handling of
unknown fields.

## References

IGS/RTCM RINEX 3.05; Unicore N4 GPSEPH ephemeris fields.
