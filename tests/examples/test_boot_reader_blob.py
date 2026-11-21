"""The shipped boot-menu reader image and its use by the example."""

import hashlib
from pathlib import Path

from examples.inav_page_capture.__main__ import DEFAULT_READER, build_parser

READER = Path(__file__).resolve().parents[2] / "tools" / "boot-reader"
BLOB = READER / "reader.bin"

READER_SHA256 = (
    "7ed2e04d4f78add28a58821880e2cb270012dc0ebd76a5343a8b6d63eb7b7358"
)


def test_reader_image_is_shipped_and_pinned() -> None:
    assert BLOB.is_file()
    assert BLOB.stat().st_size == 380
    digest = hashlib.sha256(BLOB.read_bytes()).hexdigest()
    assert digest == READER_SHA256


def test_reader_source_is_shipped_next_to_the_image() -> None:
    source = READER / "um982_ram_reader.S"
    assert source.is_file()
    text = source.read_text(encoding="ascii")
    assert "NDS32" in text
    assert "UM982RAM1" in text
    assert "0x200000" in text


def test_reader_directory_keeps_only_image_and_source() -> None:
    assert sorted(path.name for path in READER.iterdir()) == [
        "reader.bin",
        "um982_ram_reader.S",
    ]


def test_example_defaults_to_the_shipped_reader_image() -> None:
    assert DEFAULT_READER == BLOB
    parser = build_parser()
    args = parser.parse_args(["--port", "/dev/null"])
    assert args.helper == BLOB
    help_text = parser.format_help()
    assert "tools/boot-reader/reader.bin" in help_text
