# Coordinate reference transformations

Install the optional PROJ integration and transform a longitude, latitude and
ellipsoidal height to ECEF:

```bash
python -m pip install '.[geodesy]'
python -m examples.crs_transform EPSG:4979 EPSG:4978 8.0 50.0 100.0
```

Geographic input and output use longitude, latitude order. The result includes
the selected operation, its reported accuracy and PROJ versions. Supply a
coordinate epoch with `--epoch` when the source frame requires one. Select
explicit vertical CRSs and install the required grids for height transformations;
the helper rejects a transformation when PROJ reports its best operation is
unavailable. `--promote-to-3d` explicitly promotes 2D CRSs using their
ellipsoidal height; it does not select a geoid.

See the [pyproj transformation documentation](https://pyproj4.github.io/pyproj/stable/advanced_examples.html).
