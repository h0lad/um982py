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
`PositionSubscription` consumes GGA fixes from that same stream, including
while `RtkSession` forwards corrections. Its bounded queue counts dropped GGA
messages and timestamps each message when the stream dispatches it.
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

For GGA streams, `PositionMonitor` checks configurable arrival gaps, correction
age, satellite count, fix quality and straight-line displacement rate. A
displacement rate is not measured velocity, and these checks do not establish
position accuracy or navigation integrity.

`geojson_feature()` exports positions after the application establishes the
WGS 84 reference. `navsatfix()` creates an optional ROS 2 `sensor_msgs/NavSatFix`
using an application-supplied ROS timestamp and antenna frame. It does not infer
constellation usage or covariance, and requires an explicit augmented status.

## Mobile RTK

`um982py.rtk_session.RtkSession` forwards validated RTCM frames through a
running `ReceiverStream`, retries recoverable caster failures, and can request
GGA through a caller-supplied provider. Construct a fresh `NtripClient` in the
client factory on each connection, including a fresh `initial_gga` when the
caster requires it. A GGA provider should return `None` when no current fix is
available. `run(stop_event)` is blocking; run it on an application-owned
thread and handle exceptions there. Call `health()` to inspect state, connection
attempts, forwarded frames and monotonic arrival times.
The health snapshot also exposes received RTCM message counts and correction
age. Use `fetch_sourcetable()` to inspect the caster's advertised mountpoints;
distance alone does not establish that a service is suitable.
Pass an `NtripClientPool` as the client factory to rotate between explicitly
configured sources on retryable connection failures. Authentication, TLS and
receiver-write failures still stop the session.

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
connect it to the transport and replay its bytes. `SessionRecorder.mark_gap()`
records disconnects, and `iter_session_events()` reports gaps and unfinished
frame bytes instead of joining messages across interrupted connections.
Pass `close_stream=False` to `RecordingTransport` when a recorder must outlive
a receiver connection. Capture-sink failures raise `RecordingError` and stop
the session instead of triggering a receiver reconnect.
`EpochTracker` checks gaps only in the series and cadence supplied by the user.
For short diagnostic captures, `experimental.capture.BoundedRecordingTransport`
retains bytes in memory up to a limit and exposes `limit_reached`.

The [research recorder](../examples/research_session/README.md) produces a
manifest and RINEX artifacts; the [unattended recorder](../examples/unattended_station/README.md)
adds segments, disk checks and a journal. Preserve antenna metadata, physical
reference point, coordinate frame and epoch, receiver firmware, configuration,
time scale, correction source and independent field notes. Unknown values in
the manifest remain unknown; they are not inferred from a successful export.

## Coordinate reference systems

Install `um982py[geodesy]` for `transform_coordinate()`, which reports the
selected PROJ operation and rejects unavailable best operations. Use explicit
3D horizontal and vertical CRSs, coordinate epochs and transformation grids;
see the [CRS example](../examples/crs_transform/README.md). The operation's
reported accuracy is not an estimate of the receiver's position error.

## Pulse timing

`PpsDevice` reads an already configured Linux PPS device using 64-bit Python on
x86-64 or AArch64.
It returns kernel edge timestamps in host `CLOCK_REALTIME` and sequence numbers;
the host clock can step. Associate each pulse with receiver UTC independently
before using `pps_clock_offset_ns()`, and account for configured pulse delay and
timestamping uncertainty. See the [time transfer example](../examples/time_transfer/README.md).
`missed_pps_edges()` assumes both snapshots come from the same device instance;
a reset near sequence-number wrap can appear to be a normal wrap.

## Post-processed RTK

`run_ppk()` validates RINEX headers and runs an installed RTKLIB `rnx2rtkp`
with an explicit base ECEF position. It records input and executable hashes,
the command, logs and solution quality counts in a new directory. See the
[post-processing example](../examples/postprocessed_rtk/README.md) for the
required frame and antenna metadata. Validate the solution and input signal
mapping against independent field data before assigning an accuracy.

## Configuration changes

`augmentation_plan()` previews commands for a known signal group.
`enable_augmentation()` changes receiver settings and may restart acquisition;
it does not save them unless `persist=True`. Its result distinguishes a failed
readback from a verified signal group. Snapshot and restoration utilities cover
only the settings documented by `RestorableSettings`; inspect restoration
errors and remaining differences.

See the [validation matrix](validation.md) for the evidence available in this
repository and the checks needed for a deployment.
