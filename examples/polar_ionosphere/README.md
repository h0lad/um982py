# Polar ionosphere tracking timeline

Build a timeline of GPS dual-frequency code TEC, ROT, rolling ROTI, C/N₀ and
lock times alongside receiver position status and tracking-quality events.
Gaps, missing frequency pairs, decreases in lock time and signal changes reset
the rate history.

ROTI is the sample standard deviation of code-derived rates. By default, it
needs at least five rates and continuous accepted intervals spanning the full
`--roti-window-s`. Adjust these requirements with `--min-roti-coverage` and
`--min-roti-samples`. The report gives coverage as elapsed interval duration
and lists the sample count separately.

```bash
python -m examples.polar_ionosphere --port /dev/ttyUSB0 --duration 600 --json /tmp/polar.json
python -m examples.polar_ionosphere --replay tests/fixtures/captures-extra/RANGEB.bin --json /tmp/polar-replay.json
```

Hardware biases and multipath remain in code-derived TEC. These values indicate
TEC variation but are not calibrated absolute TEC or a scintillation index. The
receiver can miss cycle slips. Low-rate measurements cannot resolve variations
above their sampling bandwidth.

## References

- Unicore N4 R1.15 observation tracking status.
- IGS ionosphere monitoring.

## Compare a space-weather campaign

Generate a JSON report from each station or day, then compare independently
supplied event windows on the same GPS time scale:

```bash
python -m examples.polar_ionosphere.campaign --report station-a polar-a.json \
    --report station-b polar-b.json --events events.csv --output /tmp/storm.json
```

The event CSV has `start_gps_seconds,end_gps_seconds,event` columns. The report
counts dual-frequency samples and summarizes code ROTI and C/N₀ within each
window, retaining each input's tracking-quality report and signal frequencies.
Empty windows remain visible. Review station setups, frequency pairs and sample
rates before comparison.
