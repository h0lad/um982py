"""Tests the precipitable water vapour example."""

from __future__ import annotations

import pytest
from examples.pwv_meteorology import (
    MANUAL_TROPINFO_LINE,
    Troposphere,
    TroposphereModel,
    WaterVapour,
    manual_troposphere,
    pi_factor,
    precipitable_water_millimetres,
    tropinfo_record,
    zwd_to_pwv_ratio,
)

from um982py.messages import Record

MANUAL_ZENITH_TOTAL = 2.354103
MANUAL_DRY = 2.292246
MANUAL_WET = 0.061857
MANUAL_STD = 0.026856
PI_280_KELVIN = 0.159622
ZWD_PWV_RATIO_280_KELVIN = 6.264803
ZWD_PWV_RATIO_270_KELVIN = 6.493050
PUBLISHED_RULE_OF_THUMB_RATIO = 6.5
PRECIPITABLE_WATER_280_KELVIN_MM = 9.874


def test_manual_line_decodes_to_the_documented_delays() -> None:
    troposphere = Troposphere.from_record(tropinfo_record(MANUAL_TROPINFO_LINE))
    assert troposphere == manual_troposphere()
    assert troposphere.model is TroposphereModel.SAASTAMOINEN
    assert troposphere.zenith_total == pytest.approx(MANUAL_ZENITH_TOTAL, abs=1e-6)
    assert troposphere.dry == pytest.approx(MANUAL_DRY, abs=1e-6)
    assert troposphere.wet == pytest.approx(MANUAL_WET, abs=1e-6)
    assert troposphere.std == pytest.approx(MANUAL_STD, abs=1e-6)


def test_line_with_a_broken_checksum_carries_no_frame() -> None:
    with pytest.raises(ValueError, match="no complete frame"):
        tropinfo_record(MANUAL_TROPINFO_LINE.replace("89ed6541", "89ed6542"))


def test_manual_delays_are_self_consistent() -> None:
    troposphere = manual_troposphere()
    assert troposphere.dry_plus_wet == pytest.approx(troposphere.zenith_total, abs=1e-6)


def test_pi_at_280_kelvin_matches_the_closed_form() -> None:
    assert pi_factor(280.0) == pytest.approx(PI_280_KELVIN, abs=1e-6)


def test_reciprocal_pi_at_280_kelvin_matches_the_closed_form() -> None:
    assert zwd_to_pwv_ratio(280.0) == pytest.approx(ZWD_PWV_RATIO_280_KELVIN, abs=1e-6)


def test_rule_of_thumb_ratio_is_reproduced_at_270_kelvin() -> None:
    """The published ~6.5 ratio holds at 270 K, which is why 280 K gives 6.265."""
    assert zwd_to_pwv_ratio(270.0) == pytest.approx(
        PUBLISHED_RULE_OF_THUMB_RATIO, rel=2e-3
    )
    assert zwd_to_pwv_ratio(270.0) == pytest.approx(ZWD_PWV_RATIO_270_KELVIN, abs=1e-6)


def test_manual_wet_delay_gives_plausible_precipitable_water() -> None:
    water = WaterVapour(troposphere=manual_troposphere(), mean_temperature=280.0)
    assert water.millimetres == pytest.approx(
        PRECIPITABLE_WATER_280_KELVIN_MM, rel=5e-3
    )
    assert 0.0 < water.millimetres < 100.0


def test_water_vapour_bundles_the_factor_and_the_delay() -> None:
    water = WaterVapour(troposphere=manual_troposphere(), mean_temperature=280.0)
    assert water.pi == pytest.approx(pi_factor(280.0), abs=1e-12)
    assert water.zwd_to_pwv_ratio == pytest.approx(1.0 / water.pi, abs=1e-12)
    assert water.millimetres == pytest.approx(
        precipitable_water_millimetres(MANUAL_WET, 280.0), abs=1e-12
    )


def test_pi_falls_with_rising_mean_temperature() -> None:
    temperatures = (260.0, 270.0, 280.0, 290.0, 300.0)
    factors = [pi_factor(temperature) for temperature in temperatures]
    assert factors == sorted(factors)


def test_pi_rejects_a_non_positive_temperature() -> None:
    with pytest.raises(ValueError, match="positive"):
        pi_factor(0.0)


def test_precipitable_water_rejects_a_negative_delay() -> None:
    with pytest.raises(ValueError, match="negative"):
        precipitable_water_millimetres(-0.001, 280.0)


def test_binary_model_code_maps_to_the_named_model() -> None:
    record = Record(
        "TROPINFO",
        (
            ("trop_module", 1),
            ("tropzenith", MANUAL_ZENITH_TOTAL),
            ("dry", MANUAL_DRY),
            ("wet", MANUAL_WET),
            ("std", MANUAL_STD),
        ),
    )
    assert Troposphere.from_record(record).model is TroposphereModel.SAASTAMOINEN


def test_unknown_model_name_is_rejected() -> None:
    record = Record("TROPINFO", (("trop_module", "HOPFIELD"),))
    with pytest.raises(ValueError, match="unknown tropospheric model"):
        Troposphere.from_record(record)


def test_unknown_binary_model_code_is_rejected() -> None:
    record = Record("TROPINFO", (("trop_module", 7),))
    with pytest.raises(ValueError, match="code 7"):
        Troposphere.from_record(record)
