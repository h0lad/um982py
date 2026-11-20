# Doppler velocity

Estimate receiver velocity and clock drift from Doppler observations.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

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

The solver uses Doppler observations and broadcast ephemerides. Use
`--observer X Y Z` to supply an approximate ECEF receiver position in metres.
For comparison, `--truth-velocity VX VY VZ` accepts an independent ECEF
velocity in metres per second.

With `--compare-receiver`, capture primary-antenna `DOPPVEL` and compare speeds
with the nearest computed receiver solution. The comparison uses horizontal
and vertical speeds. `--receiver-tolerance` limits the difference between header
epochs in seconds (default 0.5).

The report includes the time offset, receiver latency and age. It applies no
latency correction or interpolation and can reuse receiver samples. A capture
without a matching `DOPPVEL` record leaves the comparison empty. Because the
receiver and solver use the same observations, their agreement is not an
independent accuracy check.

## Read native receiver Doppler velocity

Record and compare `VELDATAB` and `BESTNAVXYZB` together, or replay the same
capture with the receiver disconnected.

```bash
python -m examples.doppler_velocity.receiver_state --port /dev/ttyUSB0 \
    --baud 921600 --duration 30 --record /tmp/native-doppler.bin \
    --json /tmp/native-doppler.json
python -m examples.doppler_velocity.receiver_state --replay /tmp/native-doppler.bin
```

The report compares only computed Doppler solutions at the same GPS epoch as
the `VELDATA` measurement. Native samples appear even when the matching
reference is missing. Across 11 matched UM982 epochs, the ECEF velocity
vectors agreed exactly and the largest axis standard-deviation difference was
9.1 × 10⁻¹⁰ m/s. This compares two receiver outputs sharing a solution.

The experimental `VELDATAB` API returns the receiver's native ECEF velocity
vector in metres per second and its measurement epoch in GPS seconds.
`velocity_std_ecef_mps` gives the X, Y and Z standard deviations, and
`uncertainty_3d_mps` is their root-sum-square. These values were checked against
simultaneous `DOPPVELB`, `BESTNAVXYZB` and `BESTNAVB` reports on a UM982.

`clock_drift_mps` is the additive receiver clock term in the corrected
range-rate model, with range rate equal to negative Doppler times the carrier
wavelength. It can be compared directly with the example's Doppler clock
estimate. A calculation from simultaneous GPS L1 `RANGEB` observations and
broadcast ephemerides agreed within 0.019 m/s across 12 epochs.

```python
from um982py import Receiver
from um982py.experimental import velocity_data_read

with Receiver.connect("/dev/ttyUSB0", 921600) as receiver:
    sample = receiver.execute(velocity_data_read())
    print(sample.epoch_gps_seconds, sample.velocity_ecef_mps)
    print(sample.velocity_std_ecef_mps, sample.clock_drift_mps)
```

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
