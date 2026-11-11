# Spatial ionospheric TEC changes

Compare matched changes in slant total electron content (TEC) from two stations.

## Run

From the repository root, run the **synthetic demonstration**:

```bash
python -m examples.spatial_tec --input examples/spatial_tec/sample.csv
```

Use your CSV with `--input` and `--json result.json` to save the report.

## Input

Each row describes one satellite over an epoch interval at both stations.
Use the same two carrier frequencies, in Hz, and range-increasing carrier
phases, in metres, at each end of the interval. The phase arcs at each station
must be continuous and slip-free. Join records by constellation, satellite,
signal and epoch before preparing the CSV. The program cannot verify the join.

## Explanation and interpretation

The ionosphere delays code and advances carrier phase. Dividing the change in
`(high phase - low phase)` by `40.3 × 10^16 × (1/f_low² - 1/f_high²)` gives the
change in slant TEC units (TECU), with initial ambiguities cancelling within
continuous arcs. The report gives paired differences and Pearson correlation.
It does not map them to vertical TEC or attribute them to a particular
ionospheric structure.

Compare the result with an independently processed RINEX pair and labelled
cycle-slip intervals. Even nearby receivers observe different paths, and time
correlation reduces the effective sample size, so the reported correlation is
not a significance test.

## References

- [ESA Navipedia: Ionospheric delay](https://gssc.esa.int/navipedia/index.php/Ionospheric_Delay).
- [Library examples guide](../README.md).
