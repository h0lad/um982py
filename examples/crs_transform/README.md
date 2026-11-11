# Coordinate reference transformations

Transform longitude, latitude and ellipsoidal height to ECEF:

```bash
python -m pip install '.[geodesy]'
python -m examples.crs_transform EPSG:4979 EPSG:4978 8.0 50.0 100.0
```

Geographic input and output use longitude first, then latitude. The result
includes the selected operation, its reported accuracy and PROJ versions.
Supply a coordinate epoch with `--epoch` when the source frame requires one.

For height transformations, select explicit vertical CRSs and install the
required grids. If PROJ reports that its best operation is unavailable, the
helper rejects the transformation. `--promote-to-3d` adds ellipsoidal height to
a 2D CRS without selecting a geoid.

See the [pyproj transformation documentation](https://pyproj4.github.io/pyproj/stable/advanced_examples.html).
