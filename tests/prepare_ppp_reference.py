"""Prepare the public NYA1 PPP comparison with verified CODE products."""

from __future__ import annotations

import argparse
import gzip
from pathlib import Path

from examples.offline_ppp.__main__ import download_products

from um982py.field_data import file_sha256

FIXTURES = Path(__file__).parent / "fixtures" / "reference"
PRODUCT_HASHES = {
    "2023001.sp3": "5204bf7c3f11a87c0966ed644c23483951f2039f9bec1a2c1843210c5f652778",
    "2023001.clk": "59942569c8de8a3d894251e93e2121bf5f42639a6762b73f30f3746499ea507e",
    "2023001.bia": "ea0a838b984217f0bf81f476a30d127e172d857d6555699a2b718c31f7cc5d52",
    "2023001.nav": "03b83728b9a81b786baad88cf1bfcb943929fd02188ac8d9a43830b46bcfdf2f",
}


def prepare(directory: Path) -> None:
    """Decompress fixed public fixtures and fetch their matching products."""
    directory.mkdir(parents=True, exist_ok=False)
    for source, target in (
        ("nya1_2023001_2h.obs.gz", "station.obs"),
        ("igs20_gps_ash701073_snow.atx.gz", "antenna.atx"),
    ):
        (directory / target).write_bytes(
            gzip.decompress((FIXTURES / source).read_bytes())
        )
    products = directory / "products"
    download_products(directory / "station.obs", products, "rapid", adjacent_days=0)
    for name, expected in PRODUCT_HASHES.items():
        if file_sha256(products / name) != expected:
            raise ValueError(f"reference product hash mismatch: {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.output)


if __name__ == "__main__":
    main()
