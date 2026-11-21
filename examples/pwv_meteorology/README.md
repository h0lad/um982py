# Precipitable water vapour

Estimate precipitable water vapour from zenith wet delay.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.pwv_meteorology --port /dev/ttyUSB0 --baud 921600 \
    --json pwv.json
```

Run the published demonstration without a receiver:

```bash
python -m examples.pwv_meteorology --manual
```

## Inputs and results

`--tm` sets the water-vapour-weighted mean temperature in kelvin. The
`--manual` option uses published demonstration values instead of receiver data.
Replay exports all TROPINFO epochs unless limited with `--frames`. Each
epoch includes its raw delays and the receiver's GPST timestamp when available.
Negative wet delays and nonfinite inputs are counted and retained with a null
PWV value. The default 280 K is recorded as an assumption.

The conversion uses `PWV = Pi x ZWD` with
`Pi = 10^6 / (rho_w R_v (k3/Tm + k2'))`. The refractivity constants are the
Bevis set (`k2' = 22.13 K/hPa`, `k3 = 3.739e5 K^2/hPa`, both converted to
SI pressure units), which gives the published `ZWD/PWV` ratio of about 6.5
at 270 K. A fixed `Tm` is an assumption: for local meteorology use a measured
or modelled `Tm` (Bevis et al. give `Tm = 0.72 Ts + 70.2 K` from US radiosondes).
A receiver-reported ZWD is a model estimate, not a calibrated water-vapour
observation.

## References

- Bevis et al. (1992), *GPS Meteorology: Remote Sensing of Atmospheric Water
  Vapor Using the Global Positioning System*, JGR 97(D14) (Tm relation).
- Bevis et al. (1994), *GPS Meteorology: Mapping Zenith Wet Delays onto
  Precipitable Water*, J. Appl. Meteor. 33(3), 379-386 (conversion factor and
  refractivity constants).
- Rocken et al. (1993), *Sensing integrated water vapor along GPS ray paths*
  (the ~6.5 ZWD/PWV rule of thumb).
