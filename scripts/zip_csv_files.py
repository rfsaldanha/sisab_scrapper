#!/usr/bin/env python3
"""Convert existing CSV files to single-file .csv.zip archives."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Iterable

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.csv_zip import write_csv_bytes_zip_atomic, zip_path_for_csv

LOGGER = logging.getLogger("sisab_zip_csv_files")


def is_candidate(path: Path) -> bool:
    name = path.name
    return (
        path.is_file()
        and path.suffix == ".csv"
        and not name.startswith(".")
        and ".tmp" not in name
        and not name.endswith(".lock")
    )


def iter_csv_files(paths: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_file():
            if is_candidate(path):
                files.append(path)
            continue
        if path.is_dir():
            files.extend(item for item in path.rglob("*.csv") if is_candidate(item))
            continue
        LOGGER.warning("Skipping missing path: %s", path)
    return sorted(set(files))


def convert_csv(path: Path, dry_run: bool = False) -> bool:
    zip_path = zip_path_for_csv(path)
    action = "Overwriting" if zip_path.exists() else "Creating"
    LOGGER.info("%s %s from %s", action, zip_path, path)
    if dry_run:
        return True

    data = path.read_bytes()
    write_csv_bytes_zip_atomic(zip_path, data)
    path.unlink()
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert CSV files to .csv.zip archives, overwriting existing archives.")
    parser.add_argument("paths", nargs="*", type=Path, default=[Path("data")])
    parser.add_argument("--dry-run", action="store_true", help="Report conversions without writing archives.")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser


def run(args: argparse.Namespace) -> int:
    candidates = iter_csv_files(args.paths)
    converted = 0
    for path in candidates:
        if convert_csv(path, dry_run=args.dry_run):
            converted += 1
    LOGGER.info("%s %d CSV file(s).", "Would convert" if args.dry_run else "Converted", converted)
    return converted


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s %(message)s")
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
