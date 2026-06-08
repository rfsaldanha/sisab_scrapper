"""Helpers for storing CSV payloads as single-file ZIP archives."""

from __future__ import annotations

import contextlib
import os
import zipfile
from pathlib import Path


def zip_path_for_csv(path: Path) -> Path:
    if path.name.endswith(".csv.zip"):
        return path
    if path.suffix != ".csv":
        raise ValueError(f"Expected a .csv or .csv.zip path: {path}")
    return path.with_name(f"{path.name}.zip")


def csv_path_for_zip(path: Path) -> Path:
    if not path.name.endswith(".csv.zip"):
        raise ValueError(f"Expected a .csv.zip path: {path}")
    return path.with_name(path.name[:-4])


def csv_member_name(path: Path) -> str:
    if path.name.endswith(".csv.zip"):
        return path.name[:-4]
    if path.suffix == ".csv":
        return path.name
    raise ValueError(f"Expected a .csv or .csv.zip path: {path}")


def read_csv_zip_text(path: Path, member_name: str, encoding: str = "utf-8") -> str:
    with zipfile.ZipFile(path) as archive:
        names = [item for item in archive.namelist() if not item.endswith("/")]
        if names != [member_name]:
            raise ValueError(f"Expected ZIP {path} to contain only {member_name}; found {names}")
        return archive.read(member_name).decode(encoding)


def read_csv_text(path: Path, encoding: str = "utf-8") -> str:
    if path.name.endswith(".csv.zip"):
        return read_csv_zip_text(path, csv_member_name(path), encoding=encoding)
    return path.read_text(encoding=encoding)


def existing_csv_path(preferred_zip_path: Path) -> Path | None:
    if preferred_zip_path.exists():
        return preferred_zip_path
    legacy_path = csv_path_for_zip(preferred_zip_path)
    if legacy_path.exists():
        return legacy_path
    return None


def write_csv_zip_atomic(path: Path, text: str, encoding: str = "utf-8") -> None:
    path = zip_path_for_csv(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    member_name = csv_member_name(path)
    data = text.encode(encoding)

    with zipfile.ZipFile(temp_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member_name, data)

    if read_csv_zip_text(temp_path, member_name, encoding=encoding) != text:
        with contextlib.suppress(FileNotFoundError):
            temp_path.unlink()
        raise ValueError(f"ZIP verification failed for {path}")

    os.replace(temp_path, path)


def write_csv_bytes_zip_atomic(path: Path, data: bytes) -> None:
    path = zip_path_for_csv(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    member_name = csv_member_name(path)

    with zipfile.ZipFile(temp_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member_name, data)

    with zipfile.ZipFile(temp_path) as archive:
        names = [item for item in archive.namelist() if not item.endswith("/")]
        if names != [member_name] or archive.read(member_name) != data:
            with contextlib.suppress(FileNotFoundError):
                temp_path.unlink()
            raise ValueError(f"ZIP verification failed for {path}")

    os.replace(temp_path, path)
