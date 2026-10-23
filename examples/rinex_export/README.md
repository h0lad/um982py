# Multi-GNSS RINEX export

Export multi-GNSS RANGE or OBSV observations as RINEX 3.05, with optional
per-antenna files and a JSON omission report.

The optional JSON report also records the input capture hash (when a capture
file exists), output hashes, captured and exported counts, GPST epoch bounds,
requested capture settings and user-supplied station metadata. Since requested
settings and user metadata do not establish what the receiver actually used,
the report marks receiver configuration as unverified. Keep the original
capture file alongside the report and RINEX files.

The report includes observation validity-flag counts, duplicate signals and
reported lock-time decreases. Gaps in live captures are measured against the
requested interval, while replay does not infer gaps when the original cadence
is unknown. Lock-time decreases do not independently prove a cycle slip, and
missing flags are receiver-reported indicators.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

Connect to a receiver:

```bash
python -m examples.rinex_export --port /dev/ttyUSB0 --baud 921600 --frames 60 \
    --output /tmp/master.obs --json /tmp/rinex-report.json
```

Export both antenna inputs:

```bash
python -m examples.rinex_export --port /dev/ttyUSB0 --frames 60 --secondary \
    --output /tmp/master.obs --secondary-output /tmp/slave.obs \
    --json /tmp/rinex-report.json
```

Use the documented R1.15 OBSVM/OBSVH observation logs instead of RANGE/RANGEH:

```bash
python -m examples.rinex_export --port /dev/ttyUSB0 --source obsv \
    --frames 60 --output /tmp/obsv.obs --json /tmp/obsv-report.json
```

The library also accepts OBSVBASE records. The exporter excludes compressed
OBSVMCMP and OBSVHCMP records, whose phase values are modulo encoded.

Replay the supplied capture:

```bash
python -m examples.rinex_export \
    --replay tests/fixtures/captures-extra/RANGEB.bin --output /tmp/replay.obs \
    --json /tmp/replay-report.json
```

Replay exports every captured epoch by default. Pass `--frames` to limit it.
Live collection defaults to 60 frames unless another limit is supplied.

## Inputs and results

`--output` is the primary observation file. For a second antenna, add
`--secondary` and `--secondary-output`. The JSON report records omissions.
Supply station metadata and validate the file before using it for geodetic
processing because RANGE lacks marker coordinates.

## Understanding the result

Code and carrier phase validity are handled separately: unavailable observables
are blank, while valid values from the same signal can still be exported. Doppler
is left blank when carrier phase is invalid. The `invalid_code_or_phase` count
includes these partially valid signal records as well as wholly omitted records.

Receiver observations do not supply complete surveyed marker and antenna
metadata. Before geodetic processing, review the header and omissions and consult
the [base survey guide](../ntrip_server/SURVEY.md) for station setup.
The phase alignment between signals is unknown and is recorded as such in the
`SYS / PHASE SHIFT` header records. RINEX 3.05 says data with unknown phase
alignment should not be published as RINEX 3 observations. The blank records
are an exceptional provision for special projects and analysis. Establish the
alignment independently before publishing or using the phases for precise work.

## References

IGS/RTCM RINEX 3.05; Unicore N4 R1.4.
