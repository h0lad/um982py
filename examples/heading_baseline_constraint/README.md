# Heading with baseline-length constraint

Estimate dual-antenna heading and pitch while forcing the baseline vector to
the measured physical antenna separation.  The receiver's `BSLNENUHD` log
reports an unconstrained ENU baseline. This example projects it onto the sphere
of the supplied length using equal component weights and does not improve the
measured direction or implement a constrained GNSS estimator.

## Background

For a full observation-level baseline-length-constrained estimator, see

> Ding, W., Sun, W., Yan, H., Li, W., & Jiang, Y. (2024). Low-cost dual-antenna
> GNSS-based heading and pitch angles estimation considering baseline length
> constraint. *Measurement*, 228, 115492.
> doi:10.1016/j.measurement.2024.115492

The complete direction of the reported baseline is preserved, and only its
length is rescaled.  The result is compared with the receiver's own `UNIHEADING`
output for the same epochs.

## Run

Measure the physical distance between the two antenna phase centres and supply
it in metres:

```bash
python -m examples.heading_baseline_constraint \
    --port /dev/ttyUSB0 --baud 921600 \
    --baseline-length 1.234 \
    --duration 30 --interval 1
```

Use `--swap-antennas` if the slave antenna is routed to what the receiver
calls ANT1.

## Output

The JSON report contains, for every matched epoch:

- `constrained_heading` and `constrained_pitch` – attitude after rescaling
- `receiver_heading` and `receiver_pitch` – the `UNIHEADING` solution
- `heading_residual_deg` and `pitch_residual_deg` – difference between the two
- `unconstrained_length` – raw `BSLNENUHD` baseline length
- `unconstrained_length_error_m` – deviation from the supplied physical length

A statistics block reports RMS and standard deviation of the residuals.

## Limitations

- Uniform rescaling cannot improve heading or pitch: all directional errors are
  retained. It assumes equal component weights, not a measured covariance.
- Residuals are computed against the receiver's own heading solution, not an
  independent truth such as a calibrated total station or IMU.
- One mismatched epoch can leave a `UNIHEADING` report without a matching
  `BSLNENUHD` epoch, and those are omitted from residual statistics.
