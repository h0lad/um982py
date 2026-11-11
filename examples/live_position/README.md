# Live position

Print GGA fixes from a receiver and reconnect after a transport failure:

```bash
python -m examples.live_position /dev/ttyUSB0 --baud 921600 --interval 1
python -m examples.live_position /dev/ttyUSB0 --baud 921600 --rate-hz 10
```

The example enables GPGGA output on each connection and leaves it configured
on the receiver. Stop it with Ctrl-C. For a TCP connection, use a target such
as `tcp://host:port`.

Choose either `--interval` in seconds or `--rate-hz` in Hertz. The receiver and
firmware determine the actual output rate.

`PositionSession` reports host arrival time separately from the receiver's GGA
UTC time of day. Missing measurements remain `None`. The session does not add
heading, speed or uncertainty from other messages. `health()` exposes the
connection state and most recent fix time. Set a staleness limit and monitor
health while consuming positions.

After confirming that the receiver outputs WGS 84 coordinates, pass `--geojson`
for GeoJSON lines. GeoJSON height, when available, is ellipsoidal height.

The optional `--max-gap` and `--max-correction-age` checks report assessment
reasons with each fix. Arrival gaps are observed when the next fix arrives. To
detect an outage before the next fix, check `PositionMonitor.age()` or the
session health from another thread.

See the [Unicore receiver reference](https://en.unicore.com/uploads/file/20241219/Unicore_Reference_Commands_Manual_For_N4_High_Precision_Products_V2_EN_R1.4.pdf) for GGA output.
