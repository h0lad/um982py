# Multi-frequency cycle-slip detection

Detect cycle-slip candidates by searching the integer space of triple-frequency
geometry-free and ionosphere-free combinations.

## Background

Cycle slips break the integer continuity of carrier-phase measurements.
A geometry-free combination of two frequencies removes geometry and clock terms,
leaving mostly ionosphere and ambiguity.  A triple-frequency closure test adds a
third frequency and checks whether an integer-slip vector is consistent across
all three combinations.

This experiment follows the detector design described in

> Blewitt, G. (1990). An automatic editing algorithm for GPS data. *Geophysical
> Research Letters*, 17(3), 199-202. doi:10.1029/GL017i003p00199

## Input CSV

One row with the three carrier frequencies in Hz:

```csv
f1_hz,f2_hz,f3_hz
1575420000,1227600000,1176450000
```

## Run

```bash
python -m examples.multifrequency_slips \
    --input examples/multifrequency_slips/sample.csv
```

Optional parameters:

- `--max-cycles` – maximum integer cycle slip magnitude to search (default 1)
- `--gf-threshold-m` – geometry-free detection threshold in metres
- `--closure-threshold-m` – triple-frequency closure threshold in metres

## Output

The JSON report contains an array of candidate slip vectors, each with the
integer slips on the three frequencies and flags for geometry-free detection,
closure detection and either.

## Limitations

- The detector assumes three simultaneous frequencies on the same satellite.
- Geometry-free jumps can also be caused by rapid ionospheric changes.
- This is a candidate flag, and independent verification is needed before
  editing observations.
