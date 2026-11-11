# QZSS disaster reports

Decode and CRC-check recorded or live `QZQSM` reports. For live reception, the
receiver must track QZSS L1S, which depends on location and firmware.

```bash
python -m examples.qzss_disaster_report --replay tests/fixtures/qzqsm-example.nmea --json /tmp/qzss.json
python -m examples.qzss_disaster_report --port /dev/ttyUSB0 --duration 60 --json /tmp/qzss-live.json
```

The decoder interprets weather details for version 1 MT43 reports and preserves
other bodies and unknown codes. It checks and retains MT44 payloads without
interpreting their fields. Current DCX and historical MT44 formats use different
layouts, but the record does not identify which format applies.

A CRC detects corruption but does not authenticate the message. The report
time carries no year. This example is not a real-time warning service.

To check an official daily archive, run
`python -m examples.qzss_disaster_report.validate_archive archive.l1s`.

## References

- Unicore N4 R1.15 section 7.4.16.
- IS-QZSS-DCR-010, IS-QZSS-L1S-008 and IS-QZSS-DCX-004.
