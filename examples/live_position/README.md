# Live position

Print GGA fixes from a receiver and reconnect after a transport failure:

```sh
python -m examples.live_position /dev/ttyUSB0 --baud 921600 --interval 1
```

The example enables GPGGA output on each connection and leaves that output
configured on the receiver. Stop it with Ctrl-C. A TCP target can be supplied as
`tcp://host:port`.

`PositionSession` reports host arrival time separately from the receiver's GGA
UTC time of day. Missing measurements remain `None`; it does not combine
heading, speed or uncertainty from other messages. `health()` exposes the
connection state and most recent fix time. Applications should set their own
staleness limits and monitor the health state while consuming positions.
The optional `--max-gap` and `--max-correction-age` checks report assessment
reasons with each fix. Arrival gaps are observed when the next fix arrives;
use `PositionMonitor.age()` or the session health from another thread to detect
an outage while no fixes are arriving.
