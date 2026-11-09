"""Optional coordinate-reference transformations through pyproj and PROJ."""

from dataclasses import dataclass
from importlib import import_module
from math import isfinite


@dataclass(frozen=True, slots=True)
class CoordinateTransform:
    """A transformed coordinate and the selected PROJ operation."""

    x: float
    y: float
    z: float
    coordinate_epoch: float | None
    source_crs: str
    target_crs: str
    operation: str
    definition: str
    accuracy_m: float | None
    pyproj_version: str
    proj_version: str


def transform_coordinate(
    coordinates: tuple[float, float, float],
    source_crs: str,
    target_crs: str,
    *,
    coordinate_epoch: float | None = None,
    promote_to_3d: bool = False,
    area_of_interest: tuple[float, float, float, float] | None = None,
) -> CoordinateTransform:
    """Transform x/y/z, with longitude before latitude for geographic CRSs.

    Supply the epoch as a decimal year in the source coordinate reference
    frame. The transformation requires the relevant grids and an exact
    operation. Set ``promote_to_3d`` to promote a 2D CRS.
    """
    if len(coordinates) != 3 or not all(isfinite(value) for value in coordinates):
        raise ValueError("coordinates must contain three finite numbers")
    if coordinate_epoch is not None and not isfinite(coordinate_epoch):
        raise ValueError("coordinate epoch must be finite")
    if area_of_interest is not None and (
        len(area_of_interest) != 4
        or not all(isfinite(value) for value in area_of_interest)
        or not -180 <= area_of_interest[0] <= area_of_interest[2] <= 180
        or not -90 <= area_of_interest[1] <= area_of_interest[3] <= 90
    ):
        raise ValueError("area of interest must be west, south, east, north degrees")
    try:
        pyproj = import_module("pyproj")
    except ModuleNotFoundError as error:
        if error.name != "pyproj":
            raise
        raise ImportError(
            "install um982py[geodesy] for coordinate transformations"
        ) from error

    source = pyproj.CRS.from_user_input(source_crs)
    target = pyproj.CRS.from_user_input(target_crs)
    if promote_to_3d:
        source, target = source.to_3d(), target.to_3d()
    if len(source.axis_info) != 3 or len(target.axis_info) != 3:
        raise ValueError("source and target CRS must be three-dimensional")
    area = (
        None
        if area_of_interest is None
        else pyproj.aoi.AreaOfInterest(*area_of_interest)
    )
    group = pyproj.transformer.TransformerGroup(
        source, target, always_xy=True, area_of_interest=area, allow_ballpark=False
    )
    if not group.best_available or not group.transformers:
        raise ValueError(
            "best coordinate transformation is unavailable; check required grids"
        )
    transformer = group.transformers[0]
    if coordinate_epoch is None:
        x, y, z = transformer.transform(*coordinates, errcheck=True)
        epoch = None
    else:
        x, y, z, epoch = transformer.transform(
            *coordinates, tt=coordinate_epoch, errcheck=True
        )
    if not all(isfinite(value) for value in (x, y, z)) or (
        epoch is not None and not isfinite(epoch)
    ):
        raise ValueError("coordinate transformation produced non-finite values")
    accuracy = transformer.accuracy
    return CoordinateTransform(
        x,
        y,
        z,
        epoch,
        source.to_string(),
        target.to_string(),
        transformer.description,
        transformer.definition,
        accuracy if accuracy >= 0 else None,
        pyproj.__version__,
        pyproj.proj_version_str,
    )
