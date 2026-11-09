# API guide

`um982py` talks to a UM982 through a serial port or a transparent TCP-to-UART
gateway. The examples below assume an installed package and a configured receiver.

## Connect and read a position

```python
from um982py import Receiver

with Receiver.connect("/dev/ttyUSB0", 921600) as receiver:
    position = receiver.best_navigation()
    if position.valid:
        print(position.latitude, position.longitude, position.height_std_m)
```

Use `Receiver.connect("tcp://host:port")` for a TCP gateway. `receiver.fix()`
returns a GGA `Fix`, and `receiver.heading()` reads the dual-antenna heading.
`best_navigation()` includes velocity and receiver-estimated standard deviations.
Known solution statuses and position types use `SolutionStatus` and
`PositionType` enums; unknown receiver values remain available as reported.

For repeated GGA queries, iterate over `receiver.positions(interval=1)`.
Each iteration polls the receiver, and the interval is the pause between queries.
Breaking the loop leaves the receiver open for other operations.

During each polling query, other received messages are discarded unless you pass
an `on_message` callback. The callback receives each message in arrival order,
including messages following the reply in the same read. Messages already queued
before the query remain available through `receive()` or `drain_pending()`.
The callback runs inside the transaction and must not call receiver methods.
For `AsyncReceiver.positions()`, the callback runs in a worker thread.

## Satellites and measurements

`receiver.satellites()` returns `Satellite` objects with a constellation, PRN,
angles and `signals`. Each `SatelliteSignal` includes a name, receiver-reported
SNR and the original system and signal IDs. Unknown names are `None`.

`receiver.range_samples()` returns supported observations in SI units. For a
recorded series, use `sample_series(records)`. Optional `systems` and `signals`
filters use receiver tracking-status IDs. Observations with unknown carrier
frequencies or unusable code and phase are omitted. GLONASS frequencies use the
reported channel or an explicit `glonass_channels` mapping.

## Galileo HAS and BeiDou PPP-B2b

```python
from um982py import Receiver

with Receiver.connect("/dev/ttyUSB0", 921600) as receiver:
    ppp = receiver.start_ppp(service="E6-HAS")
    for position in ppp.positions(interval=5):
        print(position.position_type, position.horizontal_std_m)
```

`PppSession.positions()` and `AsyncPppSession.positions()` use the same
`on_message` and queued-message rules as `receiver.positions()`. The async
callback runs in the worker thread.

Use `service="B2B-PPP"` or `"AUTO"` to select another service. Setup verifies
receiver configuration and changes the signal group and service when needed.
The `PppSession` reports previous settings and which settings changed. These
settings remain active for the receiver session; setup neither saves nor restores
them. A signal-group change can restart acquisition.

`PppSolution.valid` identifies a computed PPP position, while `converged`
reports the receiver's solution type. The selected service is configuration;
check receiver evidence separately to establish which corrections were applied.

## Logs, captures and RINEX

`Log` contains both documented and extended receiver logs. Use the same type for
one-shot queries and captures:

```python
from um982py import Log, Receiver, capture_live, export_rinex

with Receiver.connect("/dev/ttyUSB0", 921600) as receiver:
    records = capture_live(receiver, Log.RANGE, duration=60)

result = export_rinex(records, marker_name="FIELD01")
result.write("field.obs")
```

`capture_live` restores the subscriptions it changes. `load_records(path, log)`
reads a saved capture, and `decode_message(data)` decodes one checksummed frame.
When binary message IDs are ambiguous, pass the intended `log` to
`decode_message`. RTCM decoding exposes its message type and payload.
`RinexExport.write()` and `RinexNavigationExport.write()` replace existing files.

## Receiver time

`message_utc(record, leap_seconds=...)` converts a timestamped record or frame
to an aware UTC `datetime`. Supply a verified GPS–UTC offset valid for the
observation epoch. For a non-GPS receiver time reference, also supply the
verified `week_scale`. `gps_to_utc(week, seconds_of_week, leap_seconds=...)`
converts an explicit GPS week and time of week. Check the receiver's time status
before using a timestamp.

## Asyncio and errors

`AsyncReceiver.connect()` provides asynchronous `fix()`, `best_navigation()`,
`heading()`, `satellites()`, `positions()` and `start_ppp()` operations. A PPP
session returned by `await receiver.start_ppp()` provides `await position()`
and `async for` over `positions()`.

Receiver and protocol errors are defined in `um982py.errors`. For example,
`ResponseTimeout` reports a missing reply, and `CommandRejected` carries the
rejected command and receiver response. See the [example catalogue](../examples/README.md)
for complete applications and `help()` on individual objects for their parameters.

Specialist tools live in their own modules: `um982py.stats` provides statistical
functions, `um982py.geometry` covers satellite geometry, `um982py.slas` decodes
SLAS corrections, and `um982py.state` handles receiver-state restoration.
