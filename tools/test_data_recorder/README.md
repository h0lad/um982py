# Receiver test recordings

Record the receiver's unmodified serial output directly to disk for replay and
decoder, RINEX, orbit and measurement tests. The recorder temporarily configures
the receiver's log output. It writes incoming bytes before decoding them for
live statistics.

The recorder does not interpolate, fill gaps or repeat measurements. It keeps
the received bytes even if the receiver sends the same epoch more than once;
frame counts are not counts of independent epochs. Check receiver timestamps
for duplicates and gaps before using a recording as a time series.

The default run is 24 hours at 921600 baud, with 30-minute segments. Ensure at
least 10 GB is free and run a short trial first to measure the actual data
rate. Use two fixed antennas and document the receiver, firmware, configuration,
each antenna and its reference point, mounting, cable and correction source in
a JSON file. Record the baseline and setup needed to interpret both inputs.

## Receiver setup

The recorder reads the current log subscriptions, enables the core profile on
the selected receiver COM port, and restores the affected subscriptions after
the run. Specify the receiver port connected to the host serial device with
`--receiver-port COM1`, `COM2` or `COM3`. Close any serial console before
starting. To inspect the commands without changing the receiver:

```bash
python -m tools.test_data_recorder.profile
```

This profile tool only prints commands. Add `--port COM1` (or COM2/COM3) to
see commands for that receiver output. The core profile includes:

| Data | Test coverage |
| --- | --- |
| OBSVM/OBSVH and RANGE/RANGEH at 1 Hz | Both antenna inputs, RINEX, phase, Doppler and cross-log comparisons |
| GPS, GLONASS, Galileo, BeiDou and QZSS ephemerides | Orbit and navigation-message checks |
| BESTNAV/BESTNAVH and BSLNENUHD | Receiver solutions and dual-antenna baseline |
| SATVIS2, RECTIME, TIME | Sky geometry and receiver timing |
| Ionosphere/UTC parameters, hardware and RTK status | Model and diagnostic decoders |

## Set the recording rate

To request 10 Hz for observation and position logs, first inspect the commands:

```bash
python -m tools.test_data_recorder.profile --port COM1 --rate-hz 10
```

Then record a short trial, substituting the host device and receiver port:

```bash
python -m tools.test_data_recorder.record /dev/ttyUSB0 /tmp/um982-trial \
    --receiver-port COM1 --baud 921600 --duration 60 --rate-hz 10
python -m tools.test_data_recorder.audit /tmp/um982-trial
```

The output directory must be new. `--rate-hz` requests that rate for OBSVM,
OBSVH, RANGE, RANGEH, BESTNAV and BESTNAVH, plus compressed observations or PPP
position logs when their optional profiles are selected. Ephemerides, baseline
and correction blocks retain their event triggers; satellite visibility, timing
and diagnostic logs retain their own intervals. Omit the option for the original
profile. The requested rate and exact commands are recorded in session metadata.

The supported command values are 1, 2, 5, 10, 20 and 50 Hz, but actual support
depends on the receiver, firmware, signal group and individual logs. The UM982
is specified for up to 20 Hz RTK and heading; 50 Hz is documented only for
specific N4 products. An accepted command does not prove the requested cadence
was delivered. High-rate dual-antenna raw observations can exceed serial or host
capacity and increase disk use considerably: measure a short trial, check counts
and timestamps, and verify the chosen baud rate before a long recording. See the
[output-rate guide](../../docs/api.md#receiver-output-rates).
