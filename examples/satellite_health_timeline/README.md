# Satellite health timeline

Write receiver-reported `SATELLITE` and GPS, Galileo, GLONASS and BeiDou
ephemeris health as time-stamped JSON events. The report keeps unknown codes
and decodes Galileo signal status only when the receiver has the associated
navigation data. The receiver log timestamp does not say when the satellite
status changed.

```bash
python -m examples.satellite_health_timeline --port /dev/ttyUSB0 --duration 65 --json /tmp/health.json
python -m examples.satellite_health_timeline --replay tests/fixtures/captures/GPSEPHA.bin --json /tmp/health-replay.json
```

The status of a missing satellite or absent log remains unknown.

## References

- Unicore N4 R1.15 SATELLITE and ephemeris logs.
- GPS IS-GPS-200N and Galileo OS SIS ICD 2.1.
