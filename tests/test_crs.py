from types import SimpleNamespace

import pytest

from um982py.crs import transform_coordinate

pyproj = pytest.importorskip("pyproj")


def test_geodetic_to_ecef_and_back() -> None:
    result = transform_coordinate((0, 0, 0), "EPSG:4979", "EPSG:4978")
    assert (result.x, result.y, result.z) == pytest.approx((6378137, 0, 0))
    assert result.source_crs == "EPSG:4979" and result.target_crs == "EPSG:4978"
    assert result.operation and result.definition and result.proj_version
    inverse = transform_coordinate(
        (result.x, result.y, result.z),
        "EPSG:4978",
        "EPSG:4979",
        coordinate_epoch=2020.0,
    )
    assert (inverse.x, inverse.y, inverse.z) == pytest.approx((0, 0, 0))
    assert inverse.coordinate_epoch == 2020


def test_two_dimensional_crs_requires_explicit_promotion() -> None:
    with pytest.raises(ValueError, match="three-dimensional"):
        transform_coordinate((0, 0, 0), "EPSG:4326", "EPSG:4978")
    result = transform_coordinate(
        (0, 0, 0), "EPSG:4326", "EPSG:4978", promote_to_3d=True
    )
    assert result.x == pytest.approx(6378137)


def test_unavailable_best_transformation_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(*args: object, **kwargs: object) -> object:
        assert kwargs["allow_ballpark"] is False
        return SimpleNamespace(best_available=False, transformers=[object()])

    monkeypatch.setattr(pyproj.transformer, "TransformerGroup", unavailable)
    with pytest.raises(ValueError, match="unavailable"):
        transform_coordinate((0, 0, 0), "EPSG:4979", "EPSG:4978")


def test_invalid_coordinate_epoch_and_area() -> None:
    with pytest.raises(ValueError, match="epoch"):
        transform_coordinate(
            (0, 0, 0), "EPSG:4979", "EPSG:4978", coordinate_epoch=float("nan")
        )
    with pytest.raises(ValueError, match="area of interest"):
        transform_coordinate(
            (0, 0, 0), "EPSG:4979", "EPSG:4978", area_of_interest=(10, 0, -10, 5)
        )
