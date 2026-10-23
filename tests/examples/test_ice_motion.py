from pathlib import Path

import pytest
from examples.ice_motion.__main__ import main


def test_empty_position_series_rejected(tmp_path: Path) -> None:
    source = tmp_path / "empty.csv"
    source.write_text("gps_seconds,x_m,y_m,z_m\n")
    with pytest.raises(ValueError, match="empty"):
        main(
            [
                "--input",
                str(source),
                "--output",
                str(tmp_path / "out.json"),
                "--reference-frame",
                "ITRF2020",
            ]
        )


def test_replay_invalid_position_breaks_velocity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from examples.ice_motion import __main__ as motion

    from um982py.messages import Record

    def position(epoch: float, status: str, east: float) -> Record:
        return Record(
            "BESTNAVXYZ",
            (
                ("epoch", epoch),
                ("p_sol_status", status),
                ("p_x", 6378137.0),
                ("p_y", east),
                ("p_z", 0.0),
            ),
        )

    records = (
        position(1, "SOL_COMPUTED", 0),
        position(2, "INSUFFICIENT_OBS", 1),
        position(3, "SOL_COMPUTED", 2),
        position(4, "SOL_COMPUTED", 4),
        position(5, "SOL_COMPUTED", float("nan")),
        position(6, "SOL_COMPUTED", 6),
        Record(
            "BESTNAVXYZ",
            (
                ("epoch", 7.0),
                ("p_sol_status", "SOL_COMPUTED"),
                ("p_x", 0.0),
                ("p_y", 0.0),
                ("p_z", 0.0),
            ),
        ),
        position(8, "SOL_COMPUTED", 8),
    )
    monkeypatch.setattr(motion, "load_records", lambda *_: records)
    monkeypatch.setattr(motion, "record_epoch", lambda row: row.real("epoch"))
    source, output = tmp_path / "capture", tmp_path / "out.json"
    source.write_bytes(b"test capture")
    assert (
        motion.main(
            [
                "--replay",
                str(source),
                "--output",
                str(output),
                "--reference-frame",
                "test",
            ]
        )
        == 0
    )
    data = json.loads(output.read_text())
    assert [row["reason"] for row in data["rejected_position_epochs"]] == [
        "solution_not_computed",
        "non_finite_position",
        "undefined_ecef_position",
    ]
    assert data["samples"][1]["velocity_ecef_mps"] is None
    assert data["samples"][1]["velocity_unavailable_reason"] == "invalid_position_epoch"
    assert data["samples"][2]["velocity_enu_mps"] == [2, 0, 0]
    assert data["samples"][3]["velocity_unavailable_reason"] == "invalid_position_epoch"
    assert data["samples"][4]["velocity_unavailable_reason"] == "invalid_position_epoch"


def test_replay_checks_order_of_rejected_epochs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from examples.ice_motion import __main__ as motion

    from um982py.messages import Record

    records = (
        Record("BESTNAVXYZ", (("epoch", 2.0), ("p_sol_status", "INSUFFICIENT_OBS"))),
        Record(
            "BESTNAVXYZ",
            (
                ("epoch", 1.0),
                ("p_sol_status", "SOL_COMPUTED"),
                ("p_x", 6378137.0),
                ("p_y", 0.0),
                ("p_z", 0.0),
            ),
        ),
    )
    monkeypatch.setattr(motion, "load_records", lambda *_: records)
    monkeypatch.setattr(motion, "record_epoch", lambda row: row.real("epoch"))
    source = tmp_path / "capture"
    source.write_bytes(b"test capture")
    with pytest.raises(ValueError, match="strictly increasing"):
        motion.main(
            [
                "--replay",
                str(source),
                "--output",
                str(tmp_path / "out.json"),
                "--reference-frame",
                "test",
            ]
        )
