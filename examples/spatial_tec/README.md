# Spatial ionospheric TEC changes

Compare matched changes in slant total electron content (TEC) from two stations.

## Run

From the `lib/um982py` project directory, run the **synthetic demonstration**:

```bash
python -m examples.spatial_tec --input examples/spatial_tec/sample.csv
```

Supply your own matched observations with `--input` and add `--json result.json`
to save the report. No receiver connection is required.

## Input

Each row is one matched satellite and epoch interval at both stations. Supply the same two carrier frequencies in Hz and range-increasing carrier phases in metres for both ends of the interval. Phases must remain on continuous, slip-free arcs at each station. Join records by constellation, satellite, signal and epoch before preparing the CSV because the program cannot verify that join.

The included observations are synthetic and do not represent an ionospheric event.

## Explanation and interpretation

The ionosphere delays code and advances carrier phase. Dividing the change in
`(high phase - low phase)` by `40.3 × 10^16 × (1/f_low² - 1/f_high²)` gives the
change in slant TEC units (TECU), with initial ambiguities cancelling within
continuous arcs. The report gives paired differences and Pearson correlation, but
it neither maps them to vertical TEC nor attributes them to a particular
ionospheric structure.

Compare the result with an independently processed RINEX pair and labelled
cycle-slip intervals. Even nearby receivers observe different paths, and time
correlation reduces the effective sample size, so the reported correlation is
not a significance test.

## References

- [ESA Navipedia: Ionospheric delay](https://gssc.esa.int/navipedia/index.php/Ionospheric_Delay).
- [Library examples guide](../README.md).
