"""RINEX exports can be saved directly."""

from pathlib import Path

from um982py import RinexExport, RinexNavigationExport


def test_observation_and_navigation_exports_write_ascii(tmp_path: Path) -> None:
    observation = RinexExport("observation\n", 1, 1, 1, {})
    navigation = RinexNavigationExport("navigation\n", 1, ())
    for name, result in (("field.obs", observation), ("field.nav", navigation)):
        path = tmp_path / name
        assert result.write(path) == path
        assert path.read_bytes() == result.text.encode("ascii")
