# RTK quality

Summarize fix type, correction age and availability.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.rtk_quality --port /dev/ttyUSB0 --baud 921600 \
    --json quality.json
```

Replay the supplied capture:

```bash
python -m examples.rtk_quality --replay tests/fixtures/captures/BESTPOSB.bin
```

## Inputs and results

The report counts fixed solutions and identifies those with corrections no
older than 10 seconds as `fresh_fixed_epochs`. Class counts distinguish `ppp` and
`ppp_converging` from float RTK.

Add `--diagnostics` to capture `RTKDOP`, `BESTSATS` and `RTKSTATUS2` alongside
the position log. The JSON keeps their receiver epochs and raw fields separately,
including the undecoded BESTSATS flags. It does not assume that records at
different times describe the same solution. Missing logs remain empty, and DOP
sentinels such as 9999 do not represent measured geometry.

## References

Unicore N4 R1.4 interface guide.

## Inspect satellite state transitions

The experimental `MATCHEDSOLUTIONB` reader records receiver-reported satellite
status codes and numeric values:

```bash
python -m examples.rtk_quality.matched_solution --port /dev/ttyUSB0 --baud 921600 \
    --duration 60 --record /tmp/matched.bin --json /tmp/matched.json
python -m examples.rtk_quality.matched_solution --replay /tmp/matched.bin \
    --json /tmp/matched-replay.json
```

The report lists changes between successive observations within `--max-gap`.
Raw codes and values have no assigned signal identities, physical units or
phase conventions. Known codes include their receiver labels. Unknown codes
stay unlabelled. Record independent labels alongside the capture before
interpreting these fields. OEM-style message timestamps use GPS time.

## Inspect engine covariance and satellite states

The experimental `RTKDATAB`/`RTKDATA2B` reader records the engine covariance
matrix and per-satellite states:

```bash
python -m examples.rtk_quality.engine_state --port /dev/ttyUSB0 --baud 921600 \
    --duration 60 --record /tmp/engine.bin --json /tmp/engine.json
python -m examples.rtk_quality.engine_state --replay /tmp/engine.bin \
    --json /tmp/engine-replay.json
```

For each epoch, the report lists covariance diagonals and satellite identities
with their raw status codes and values. Unknown identifiers stay unresolved.
The variances describe the engine's state and cannot measure position error.
RTKDATA frames appear only while the engine uses corrections. Without these
frames, the report marks the capture as insufficient data.

## Compare environments or positioning campaigns

Generate a JSON report with `python -m examples.rtk_quality --replay CAPTURE
--json quality.json`. Repeat for each capture, then compare them:

```bash
python -m examples.rtk_quality.compare_campaigns \
    --campaign standalone standalone.json --campaign rtk rtk.json \
    --labels environments.csv --truth-error independent-errors.csv \
    --output /tmp/campaign.json
```

Labels are optional CSV rows with `start_gps_seconds,end_gps_seconds,environment`.
Intervals are non-overlapping and include the start but exclude the end.
Unlabelled epochs remain visible. Independently calculated position errors can
be supplied in `gps_seconds,error_m` rows in metres. Match them to the same GPS
time scale, frame and physical antenna point before use.

For each environment, the report gives sample counts, availability, fix classes
and correction ages for available RTK float and fixed solutions. It also lists
input hashes and gaps between recorded epochs. More than one epoch can match
the same error sample.

An optional `--cn0` CSV with `gps_seconds,cn0_dbhz` adds a nearest-sample C/N₀
summary using the same matching window. Independently verify which signal each
value represents.

An outage interval starts at the first unavailable sample. Its actual onset
between observations is unknown. A gap, environment change or end of data
censors an interval still awaiting recovery.

Availability is a fraction of received samples and does not measure the fraction
of elapsed time. Unlabelled or differing conditions prevent a controlled
comparison. Position errors must come from the supplied reference data. The
script does not derive them from receiver sigma.
