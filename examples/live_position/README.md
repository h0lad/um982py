# Live position

Print GGA fixes from a receiver and reconnect after a transport failure:

```bash
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
Pass `--geojson` for GeoJSON lines after confirming the receiver outputs WGS 84
coordinates. GeoJSON height, when available, is ellipsoidal height.
The optional `--max-gap` and `--max-correction-age` checks report assessment
reasons with each fix. Arrival gaps are observed when the next fix arrives;
use `PositionMonitor.age()` or the session health from another thread to detect
an outage while no fixes are arriving.

See the [Unicore receiver reference](https://en.unicore.com/uploads/file/20241219/Unicore_Reference_Commands_Manual_For_N4_High_Precision_Products_V2_EN_R1.4.pdf) for GGA output.
