# RINEX navigation export

Export the receiver's GPS (`GPSEPH`), Galileo (`GALEPH`) and BeiDou (`BDSEPH`)
broadcast ephemerides as a RINEX 3.05 navigation file. Use this alongside an observation file from
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

Select other constellations with `--systems GPS GAL BDS`. Before including BDS,
verify the receiver's ephemeris time convention and supply
`--bdseph-time-scale BDT` or `--bdseph-time-scale GPST`. The command preserves
repeated messages; a Galileo record produces separate I/NAV and F/NAV messages,
so the message count is not a count of distinct satellites.

## Understanding the result

The receiver does not expose every navigation field required by RINEX. GPS L2
codes, the L2 P-data flag and fit interval remain blank. Transmission time uses
the RINEX unknown-time sentinel, because the receiver's `tow` field is not
independently established as the message transmission time. The report lists
the unknown fields rather than filling in assumed values. Galileo I/NAV source
signals are not identified by the receiver and remain unset; export requires
both F/NAV and I/NAV health fields. GLONASS and BDS-3 CNAV are not exported.

The manual describes BeiDou clock time as GPS-referenced, but its example
matches the same numeric time in DLR's BDT RINEX record. This single comparison
does not establish the convention for every firmware or log. Verify it against
an independent broadcast file for the receiver being used. The selected
convention is recorded in the output header.

For downstream processing, use ephemerides covering the same satellites and
times as the observation file, and inspect the receiving tool's handling of
unknown fields.

## References

IGS/RTCM RINEX 3.05; Unicore N4 ephemeris fields;
[DLR's multi-GNSS broadcast record](https://igs.bkg.bund.de/root_ftp/IGS/BRDC/2021/364/BRDM00DLR_S_20213640000_01D_MN.rnx.gz).
