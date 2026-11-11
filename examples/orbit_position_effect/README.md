# Satellite state error projected into position

Estimate the linearized position effect of satellite orbit and clock differences
for one epoch.

## Run

From the repository root, run the **synthetic demonstration**:

```bash
python -m examples.orbit_position_effect --input examples/orbit_position_effect/sample.csv
```

Use your CSV with `--input` and `--json result.json` to save the report.

## Input

Each row supplies a satellite's unit line of sight `u_x,u_y,u_z` from receiver
to satellite, ECEF position difference `dx_m,dy_m,dz_m` and clock difference
`clock_delta_s` in seconds. Both differences use perturbed minus reference.
Each row also needs a positive weight. All rows must describe the same epoch
and use compatible frame, clock and signal conventions.

## Explanation and interpretation

For fixed observations, the induced residual is `-u·delta_sat + c × delta_clock`.
Weighted least squares solves `H delta = residual` with `H = [-u_x,-u_y,-u_z,1]`,
giving the modeled ECEF position and receiver clock changes in metres. The
calculation rejects singular geometry.

Prepare state differences from independent broadcast and precise products at the
same epochs, accounting for transmission time, reference frames, satellite
antenna reference points and clock or signal biases.

## References

- [ESA Navipedia: Positioning error](https://gssc.esa.int/navipedia/index.php/Positioning_Error).
- [Library examples guide](../README.md).
