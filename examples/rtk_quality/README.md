# RTK quality

Summarizes fix type, correction age, and availability.
`fresh_fixed_epochs` counts fixed solutions with corrections no older than 10 seconds.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

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
older than 10 seconds as `fresh_fixed_epochs`. The capture duration and interval
determine the observation window. Class counts distinguish `ppp` and
`ppp_converging` from float RTK.

Add `--diagnostics` to capture `RTKDOP`, `BESTSATS` and `RTKSTATUS2` alongside
the position log. The JSON keeps their receiver epochs and raw fields separately,
including the undecoded BESTSATS flags. It does not assume that records at
different times describe the same solution. Missing logs remain empty, and DOP
sentinels such as 9999 do not represent measured geometry.

## Understanding the result

The reported solution types and correction ages depend on the observation
window and receiver configuration. A fixed solution or recent correction age
does not establish absolute accuracy, which also depends on the base coordinates.

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
Codes and values are kept without assigning signal identities, physical units or
phase conventions. Recognized receiver labels accompany their raw codes, while
unknown codes remain unlabelled. A change is not proof of a cycle slip or ambiguity fix.
Capture data alongside independent labels before drawing conclusions. Legacy
message timestamps are interpreted as GPS time.

## Inspect engine covariance and satellite states

The experimental `RTKDATAB`/`RTKDATA2B` reader records the engine covariance
matrix and per-satellite states:

```bash
python -m examples.rtk_quality.engine_state --port /dev/ttyUSB0 --baud 921600 \
    --duration 60 --record /tmp/engine.bin --json /tmp/engine.json
python -m examples.rtk_quality.engine_state --replay /tmp/engine.bin \
    --json /tmp/engine-replay.json
```

The report lists per-epoch covariance diagonals alongside resolved satellite
identities with their raw status codes and values. Unmapped identifiers stay
unresolved rather than guessed. Variances describe the engine state, not
measured position error. RTKDATA frames only appear while the engine runs on
corrections; without them the report marks the capture as insufficient data.

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
time scale, frame and physical antenna point before use. The report includes
per-environment counts, sample-based availability, fix classes, correction
ages for available RTK float and fixed solutions, input hashes, and gaps between
successive recorded epochs. Nearest error
samples can be reused. An optional `--cn0` CSV with `gps_seconds,cn0_dbhz`
adds a nearest-sample C/N₀ summary using the same matching window. Independently
verify which signal each value represents.

Observed unavailable-to-available intervals start at the first unavailable
sample, so their actual onset is unknown. A gap, environment change or end of
data censors a pending interval. A fraction of received samples is not a fraction of
elapsed time, and unlabelled or differing conditions prevent a controlled
comparison. The script does not calculate position errors from receiver sigma.
