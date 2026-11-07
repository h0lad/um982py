# Validation and deployment evidence

| Area | Evidence in this repository | Remaining deployment work |
| --- | --- | --- |
| Serial, TCP and mixed frames | Transport, parser and recorded-frame tests | Validate the actual receiver, adapter, baud rate and sustained load. |
| Receiver commands | Replay tests and opt-in live hardware tests | Run against the intended UM982 firmware and settings; retain the hardware report. |
| NTRIP | Client, caster and reconnect tests; optional third-party clients | Test the chosen provider, credentials, GGA policy, outages and correction latency. |
| RINEX and scientific processing | Fixture and independent-reference tests; some external tools are optional | Validate the generated products, antenna metadata, frame, time and analysis against independent references. |
| Long-running recording | Segmentation, journaling, disk and restart tests | Soak-test power loss, storage exhaustion, link loss and recovery on the target system. |

The project targets UM982. UM960 and UM980 compatibility is untested. A
firmware version is supported for a deployment only after testing it with the
required messages and commands. Some tests require a receiver, external tools or
reference datasets and are skipped when those are unavailable; inspect the
test report instead of treating a passing default run as hardware validation.

Record the device model, firmware, antenna and mount, operating system, Python
version, transport, configured message rates and test duration with each
hardware report. Exercise unplug/replug, power interruption, corrupt frames,
NTRIP loss and recovery, full storage and restart. Compare independently
surveyed positions and raw measurements where the application depends on them.
