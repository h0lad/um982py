# Satellite state error projected into position

Estimate the linearized position effect of satellite orbit and clock differences for one epoch.

## Run

From the `lib/um982py` project directory, run the **synthetic demonstration**:

```bash
python -m examples.orbit_position_effect --input examples/orbit_position_effect/sample.csv
```

Supply your own satellite state differences with `--input` and add
`--json result.json` to save the report. No receiver connection is required.

## Input

One row per satellite supplies unit line of sight `u_x,u_y,u_z` from receiver to satellite, ECEF satellite position difference `dx_m,dy_m,dz_m` (perturbed minus reference), satellite clock difference `clock_delta_s` in seconds with the same sign convention, and a positive weight. All rows must describe the same epoch and compatible frame, clock and signal conventions.

The included state differences are synthetic and do not measure orbit accuracy.

## Explanation and interpretation

For fixed observations, the induced residual is `-u·delta_sat + c × delta_clock`.
Weighted least squares solves `H delta = residual` with `H = [-u_x,-u_y,-u_z,1]`,
giving the modeled ECEF position and receiver clock changes in metres. The
calculation rejects singular geometry.

Prepare state differences from independent broadcast and precise products at the
same epochs, accounting for transmission time, reference frames, satellite
antenna reference points and clock or signal biases. The linearized model does
not replace a full positioning engine or measure receiver error.

## References

- [ESA Navipedia: Positioning error](https://gssc.esa.int/navipedia/index.php/Positioning_Error).
- [Library examples guide](../README.md).
