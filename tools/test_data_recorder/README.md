# Receiver test recordings

Record serial output for replay and tests of decoders, RINEX, orbits and
measurements. The recorder writes received bytes before decoding them for live
statistics.

The recording preserves receiver bytes without interpolation, gap filling or
duplication, including repeated epochs. Check timestamps for distinct epochs
and gaps.

The default is 24 hours at 921600 baud in 30-minute segments. Keep at least
10 GB free and measure the data rate in a short trial first.

Use two fixed antennas. Record the receiver model, firmware, configuration and
correction source in a JSON file. For each antenna, record its model, reference
point, mount and cable. Include the baseline and which antenna uses each input.

## Receiver setup

Close any serial console that uses the receiver. Select the receiver port
connected to the host with `--receiver-port COM1`, `COM2` or `COM3`. The recorder
reads the current subscriptions, enables the core profile on that port and
restores the affected subscriptions when the run ends.

To inspect the commands without changing the receiver:

```bash
python -m tools.test_data_recorder.profile
```

Use `--port COM1` (or COM2/COM3) to select the receiver output. The core
profile includes:

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

Replace the host device and receiver port, then make a short recording:

```bash
python -m tools.test_data_recorder.record /dev/ttyUSB0 /tmp/um982-trial \
    --receiver-port COM1 --baud 921600 --duration 60 --rate-hz 10
python -m tools.test_data_recorder.audit /tmp/um982-trial
```

Choose a new output directory. `--rate-hz` sets the requested rate for OBSVM,
OBSVH, RANGE, RANGEH, BESTNAV and BESTNAVH. It also applies to compressed
observations and PPP position logs if you enable those optional profiles.
Ephemerides, baseline and correction blocks keep their event triggers. Satellite
visibility, timing and diagnostic logs keep their profile intervals. Without
`--rate-hz`, all logs use the original profile.

The session metadata records the requested rate and commands.

The tool accepts 1, 2, 5, 10, 20 and 50 Hz. The rates the receiver can deliver
depend on its model, firmware, signal group and selected logs. Unicore specifies
up to 20 Hz for UM982 RTK and heading. The N4 documentation lists 50 Hz only for
specific products. Check the recorded timestamps to measure the delivered rate.

High-rate observations from both antennas can exceed serial or host capacity
and consume more disk space. Check the trial recording's counts and timestamps
against the requested rate and baud rate. See the
[output-rate guide](../../README.md#receiver-output-rates).
