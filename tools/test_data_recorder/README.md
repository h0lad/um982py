# Receiver test recordings

Record the receiver's unmodified serial output directly to disk for replay and
decoder, RINEX, orbit and measurement tests. The recorder temporarily configures
the receiver's log output. It writes incoming bytes before decoding them for
live statistics.

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