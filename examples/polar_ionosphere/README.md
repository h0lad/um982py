# Polar ionosphere tracking timeline

Combine GPS dual-frequency code-derived slant TEC proxy, ROT, rolling ROTI,
C/N₀ and lock times with receiver position status and tracking-quality events.
The rate history resets at gaps, missing frequency pairs, falling lock times or
signal changes. ROTI uses the sample standard deviation of code-derived rates.
By default, it is reported only when continuous accepted rate intervals cover
the entire `--roti-window-s` and at least five rates are available. Adjust these
requirements explicitly with `--min-roti-coverage` and `--min-roti-samples`.
Coverage is elapsed interval duration, not a count of expected samples. Each
report includes both coverage and sample count. These checks do not establish
that the measurements are free of cycle slips or code outliers.

```bash
python -m examples.polar_ionosphere --port /dev/ttyUSB0 --duration 600 --json /tmp/polar.json
python -m examples.polar_ionosphere --replay tests/fixtures/captures-extra/RANGEB.bin --json /tmp/polar-replay.json
```

Code-derived TEC includes hardware biases and multipath, making it a proxy rather than
calibrated absolute TEC or a scintillation index. The receiver can miss cycle
slips, and these low-rate measurements cannot resolve variations above their
sampling bandwidth.

## References

Unicore N4 R1.15 observation tracking status; IGS ionosphere monitoring.

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
Empty windows remain visible. Matching an event in time does not establish its
cause, and different station setups, frequency pairs and sample rates need
independent review before comparison.
