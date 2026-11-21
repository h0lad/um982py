# Klobuchar model and TEC

Compare Klobuchar delay with dual-frequency TEC.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.klobuchar_vs_tec --port /dev/ttyUSB0 --baud 921600 \
    --json ionosphere.json
```

Replay the supplied capture:

```bash
python -m examples.klobuchar_vs_tec \
    --replay tests/fixtures/captures-live/RANGEA.bin \
    --ionosphere tests/fixtures/captures-live/GPSIONA.bin \
    --satvis tests/fixtures/captures-live/SATVIS2A.bin \
    --position tests/fixtures/captures-live/BESTPOSA.bin
```

## Inputs and results

Replay needs RANGE observations and companion ionosphere, satellite-visibility
and position captures. Supply these with `--ionosphere`, `--satvis` and
`--position`. The selected position must be computed and lie within
`--position-tolerance` (default one second) of the RANGE epoch. Visibility is
joined at that RANGE epoch. The example skips startup records without a
complete match and uses the most recent recorded GPSION at or before the
selected epoch. Supply coefficients valid for the same period. The report
includes separate GPST timestamps for the observations, position and GPSION.
Both live and replay modes honor the selected antenna and role swap.

## Understanding the result

Match the position, visibility, model and observation epochs.

The code-derived delay retains uncalibrated receiver and satellite biases.
The report omits relative differences when that delay is at or below 0.01 m.
The signed and absolute differences remain available in metres.

The broadcast model returns a slant L1 delay at the ionospheric pierce point;
this example divides it by the Klobuchar obliquity factor `F = 1 + 16(0.53 -
E/180)^3` to compare a vertical delay with the dual-frequency measurement
mapped by the same factor. The amplitude/period polynomials refer to the pierce
point, not the observer's zenith, so the comparison remains approximate.

## References

- Klobuchar (1987), *Ionospheric Time-Delay Algorithm for Single-Frequency GPS
  Users*, IEEE Trans. Aerospace and Electronic Systems 23(3), 325-331.
- IS-GPS-200, section 20.3.3.3.3.2 (broadcast ionospheric correction algorithm).
- [ESA Navipedia: Klobuchar ionospheric model](https://gssc.esa.int/navipedia/index.php/Klobuchar_Ionospheric_Model).
