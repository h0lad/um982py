# Doppler velocity

Solves receiver velocity and clock drift from Doppler.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

Connect to a receiver:

```bash
python -m examples.doppler_velocity --port /dev/ttyUSB0 --baud 921600 \
    --duration 60 --record captures/doppler.bin --json velocity.json
```

Replay the supplied capture:

```bash
python -m examples.doppler_velocity \
    --replay tests/fixtures/specialist/rtklib-motion.bin \
    --truth-velocity 0.03 -0.02 0.01 --json /tmp/doppler.json
```

## Inputs and results

The solver uses Doppler observations and broadcast ephemerides. `--observer X Y
Z` supplies an approximate ECEF receiver position in metres, while `--truth-velocity
VX VY VZ` supplies independent ECEF velocity in metres per second for
comparison.

Add `--compare-receiver` to capture primary-antenna `DOPPVEL` and compare
computed horizontal and vertical speeds with the nearest computed Doppler
solution. `--receiver-tolerance` sets the maximum header-epoch difference in
seconds (default 0.5). The report includes the time offset, receiver latency and
age, but does not correct for latency or interpolate. Receiver samples can be
reused. The receiver and solver share observations, so this comparison is not an
independent accuracy test. Captures without a matching `DOPPVEL` record leave
the comparison empty.

## Understanding the result

Doppler is the frequency shift associated with relative motion between
receiver and satellite. This example uses observations and broadcast orbits to
estimate receiver velocity and clock drift.

The optional truth velocity is an independently known comparison in
Earth-centred X/Y/Z axes, and you can omit it when unavailable. A result is not
independently validated merely because the solver returns a value.

## References

Kaplan & Hegarty (2017), Understanding GPS/GNSS.

## Buoy vertical-motion spectrum

Capture a journey report or supply a CSV with `gps_seconds,vertical_velocity_mps`
columns. The following example analyzes non-overlapping 256-sample windows and
compares them with an optional independent wave-sensor CSV:

```bash
python -m examples.doppler_velocity.wave_buoy --journey buoy-journey.json \
    --interval-s 1 --window-samples 256 --min-frequency-hz 0.04 \
    --max-frequency-hz 0.4 --reference wave-sensor.csv --output /tmp/waves.json
```

The reference CSV uses `gps_seconds,significant_height_m`. Its timestamp is
matched to the GNSS window midpoint within `--match-window-s`. Gaps and invalid
velocities break a window. Incomplete windows are counted and excluded. The
requested frequency band must contain resolved Fourier bins and stay below
Nyquist. The output includes spectral densities, the selected band, spectral
resolution and significant height from the band-limited displacement variance.

The result describes vertical antenna motion. Buoy tilt, draft, antenna
mounting and GNSS noise are not corrected, and low-frequency noise can dominate
the spectrum. Confirm the reference sensor's timing and processing band before
comparing heights.
