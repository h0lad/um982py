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

For more coverage, pass `--compressed` to the recorder for OBSVMCMP/OBSVHCMP,
or `--corrections` for PPP, RTCM, Galileo E6 and BeiDou PPP-B2b diagnostics.
The profile tool accepts the same options. Output availability depends on the
receiver, signal reception, firmware and enabled correction services; a zero
count for an optional service does not establish a failure. The logs alone do
not prove that a correction was applied or that a phase measurement is correct.

The recorder checks command responses and stops if a requested log is rejected
or its subscription snapshot cannot be read. Restoration is attempted on
normal completion, interruption and configuration failure; a disconnect or
abrupt process termination can prevent restoration. Check the receiver's log
configuration if restoration fails. Confirm that the combined output fits the
configured port and baud rate. The 1 Hz dual-antenna observations can be
substantial; measure the trial rate and reduce optional logs or increase baud if
necessary. `ONCHANGED` alone does not guarantee a complete initial ephemeris
set. The recorder does not change signal groups, antenna power or correction
service settings.

## Capture and verify

Install the project as described in the root README. Replace the port, paths and
metadata with your setup. The output directory must not already exist.

```bash
python -m tools.test_data_recorder.record /dev/ttyUSB0 /path/to/trial --receiver-port COM1 \
    --metadata /path/to/metadata.json --duration 600
python -m tools.test_data_recorder.audit /path/to/trial
python -m tools.test_data_recorder.record /dev/ttyUSB0 /path/to/session --receiver-port COM1 \
    --metadata /path/to/metadata.json
python -m tools.test_data_recorder.audit /path/to/session
python -m tools.test_data_recorder.audit /path/to/session --export /path/to/capture.bin
```

The metadata file must contain a JSON object. `--baud`, `--duration`,
`--segment-seconds` (default 1800), `--segment-bytes` (default 256 MiB) and
`--status-seconds` (default 60) override the defaults. A segment also closes at
the size limit; time boundaries follow reads, not GNSS epoch boundaries.
Completed segments and journal entries are synchronized by default; use
`--no-fsync` to disable this. The current segment is flushed every five seconds
but is only synchronized at segment completion. Recording stops on a
transport error rather than silently reconnecting. Ctrl-C closes the capture
and writes an `interrupted` status. A disk or process failure may leave an
incomplete session or `.part` file; retain those files for inspection.

Each `segment-*.bin` contains the original bytes, including invalid or partial
frames. `segments.jsonl` records each completed segment's size, SHA-256 and
host timestamps; `session.json` contains the session metadata. `capture.json`
records elapsed time, byte count and whether the duration completed. A closed
journal alone does not mean the requested duration was reached. A transport
error records a gap and an incomplete run; the audit refuses sessions with a
gap so it cannot accidentally join frames across an interruption.
The stream also contains receiver responses and any data read while setting up
or restoring subscriptions. `capture.json` byte and frame counts cover the
timed recording interval; the offline audit includes those additional bytes.
The session metadata records the requested commands and receiver port.

During capture, JSON status lines on standard error show elapsed time, total
and recent data rate, free disk space, frame counts, decoder errors and the
age of the last OBSVM and OBSVH frames. `null` means no frame has arrived yet.
At 1 Hz, a growing age or a substantially low count for either antenna is a
reason to check its antenna, receiver configuration and output capacity.
These are host arrival times and counts, not proof of complete measurement
epochs. The live decoder adds processing load; keep the baud rate and log mix
within the capacity of the host and port. The raw bytes are saved before this
processing, but loss before a read remains possible.

The separate audit verifies segment hashes, then reports profile binary log counts,
decoder errors, discarded and pending bytes. `other_frames` includes messages
outside the listed binary logs. Error counts are lower bounds because the
decoder retains at most 32 errors per input chunk. An all-clear does not prove
that complete frames were not lost before arriving at the process. Compare the
observed log counts with the enabled rates and retain the raw session as the
reference dataset. `--export` additionally writes the verified, gap-free stream
to a new file suitable for existing replay examples. It refuses to overwrite an
existing file. A capture ending in a partial frame can still be exported; check
the audit and capture status before using it as a test fixture.

Existing APIs can verify and stream the session without loading it into memory:
`um982py.session.iter_session_bytes()` yields raw chunks and
`iter_session_frames()` yields decoded messages while rejecting recorded gaps.
Do not concatenate data across a recorded gap. Independent IGS products and
reference receivers are still needed for physical validation.
Frame counts establish the presence of checksummed messages, not successful body
decoding or complete coverage of every satellite, signal, epoch or fix state.
