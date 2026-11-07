# Integration guide

The installed package contains the `um982py` library and CLI. The examples
run from a source checkout; they are demonstrations and research workflows,
not installed applications. Select receiver logs and rates for the transport
bandwidth and the needs of the application.

## Live position and telemetry

For a synchronous one-shot query use `Receiver.best_navigation()` or
`Receiver.read_log()`. `PositionSession` reconnects a receiver and yields GGA
fixes with host arrival times; see the [live position example](../examples/live_position/README.md).
For continuous messages and commands use
`um982py.streaming.ReceiverStream`: subscribe before starting it and route
all operations on that receiver through the stream while it is running.
Each subscriber has a bounded queue. New messages are dropped when it is full;
check `Subscription.dropped` and `ReceiverStream.health()` regularly.
Command responses are returned to their caller, while unrelated messages are
delivered to subscribers. An in-flight command can delay message delivery and
other commands until it completes; set appropriate command timeouts.

The [telemetry bridge](../examples/telemetry_bridge/README.md) demonstrates a
bounded consumer and reports dropped messages. Applications using
`ReceiverStream` must manage receiver reconnections and account for data lost
outside the Python process.

`um982py.assessment.assess_position` applies application-selected limits to
reported solution status, ages and standard deviations. Provide epoch age in a
known compatible time scale, and supply horizontal and vertical uncertainty
when using those limits. Missing or invalid values fail a configured check.
The result does not establish absolute accuracy or navigation integrity.
Air, marine and vehicle uses require system-level validation appropriate to
their intended operation.

## Mobile RTK

`um982py.rtk_session.RtkSession` forwards validated RTCM frames through a
running `ReceiverStream`, retries recoverable caster failures, and can request
GGA through a caller-supplied provider. Construct a fresh `NtripClient` in the
client factory on each connection, including a fresh `initial_gga` when the
caster requires it. A GGA provider should return `None` when no current fix is
available. `run(stop_event)` is blocking; run it on an application-owned
thread and handle exceptions there. Call `health()` to inspect state, connection
attempts, forwarded frames and monotonic arrival times.

The session does not select rover mode or restore receiver settings. The
`examples.ntrip_client.managed` module demonstrates the library APIs in a source
checkout. Configure
the receiver explicitly before starting the stream. Authentication, TLS and
receiver-write failures stop the session; a caller should surface those errors
instead of retrying indefinitely. A failing GGA provider stops the session as
well. Stop the session before closing the stream.
The [NTRIP client example](../examples/ntrip_client/README.md) includes
additional receiver and reference-station diagnostics.

## Scientific sessions

`um982py.stream_capture.iter_live_records` yields records without retaining the
entire session. Close the iterator when stopping early to restore temporary log
subscriptions. Its caller processes records in the reader thread, so a slow
sink can still cause upstream loss. `RecordingTransport` records received bytes
for subsequent replay. `SessionRecorder` supplies a segmented sink with a
hash journal and explicit incomplete-session handling; the
[field recording example](../examples/field_recording/README.md) shows how to
connect it to the transport and replay its bytes.
`EpochTracker` checks gaps only in the series and cadence supplied by the user.
For short diagnostic captures, `experimental.capture.BoundedRecordingTransport`
retains bytes in memory up to a limit and exposes `limit_reached`.

The [research recorder](../examples/research_session/README.md) produces a
manifest and RINEX artifacts; the [unattended recorder](../examples/unattended_station/README.md)
adds segments, disk checks and a journal. Preserve antenna metadata, physical
reference point, coordinate frame and epoch, receiver firmware, configuration,
time scale, correction source and independent field notes. Unknown values in
the manifest remain unknown; they are not inferred from a successful export.

## Configuration changes

`augmentation_plan()` previews commands for a known signal group.
`enable_augmentation()` changes receiver settings and may restart acquisition;
it does not save them unless `persist=True`. Its result distinguishes a failed
readback from a verified signal group. Snapshot and restoration utilities cover
only the settings documented by `RestorableSettings`; inspect restoration
errors and remaining differences.

See the [validation matrix](validation.md) for the evidence available in this
repository and the checks needed for a deployment.
