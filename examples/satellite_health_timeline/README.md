# Satellite health timeline

This example writes receiver-reported `SATELLITE` and GPS, Galileo, GLONASS and
BeiDou ephemeris health as time-stamped JSON events. It retains unknown codes and
decodes Galileo signal status only when the associated navigation data were
received. Each timestamp comes from the receiver log and does not establish when
the satellite status changed.

```bash
python -m examples.satellite_health_timeline --port /dev/ttyUSB0 --duration 65 --json /tmp/health.json
python -m examples.satellite_health_timeline --replay tests/fixtures/captures/GPSEPHA.bin --json /tmp/health-replay.json
```

The status of a missing satellite or absent log remains unknown. Reported health
alone does not establish signal availability or use in a position solution.

## References

Unicore N4 R1.15 SATELLITE and ephemeris logs; GPS IS-GPS-200N and Galileo OS
SIS ICD 2.1.
