#!/usr/bin/env python3
"""Download SISAB Saude Procedimento columns as tidy CSV."""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.sisab_saude_producao import (
    BASE_URL,
    LINE_MUNICIPIO,
    REPORT_PATH,
    REPORT_URL,
    JsForm,
    JsonLogFormatter,
    SisabClient,
    SisabError,
    cache_lock,
    expand_competencias,
    parse_br_integer,
    raw_cache_path,
    valid_competencia,
    write_text_atomic,
)


COLUMN_PROCEDIMENTO = "PRC"
TP_PRODUCAO_PROCEDIMENTO = "7"
PROCEDIMENTO_SELECT_ID = "procedimento"
LOGGER = logging.getLogger("sisab_saude_procedimento")
TIDY_FIELDNAMES = [
    "competencia",
    "uf",
    "ibge",
    "municipio",
    "procedimento",
    "valor",
]


@dataclass(frozen=True)
class ReportForm:
    client: SisabClient
    procedimentos: list[str]


def new_client(args: argparse.Namespace) -> SisabClient:
    return SisabClient(
        delay=args.delay,
        timeout=args.timeout,
        retries=args.retries,
        retry_backoff=args.retry_backoff,
        retry_backoff_max=args.retry_backoff_max,
    )


def open_report(args: argparse.Namespace) -> ReportForm:
    client = new_client(args)
    try:
        response = client._request("GET", REPORT_URL)
        soup = BeautifulSoup(response.text, "html.parser")

        form = soup.find("form", id="j_idt44")
        if form is None:
            raise SisabError("Could not find SISAB report form j_idt44.")

        view_state = client._view_state_from_soup(form)
        competencia = form.find("span", id="competencia")
        competencia_select = competencia.find("select", attrs={"name": True}) if competencia else None
        if competencia_select is None:
            raise SisabError("Could not find competencia select field.")

        procedimento_select = soup.find("select", id=PROCEDIMENTO_SELECT_ID)
        if procedimento_select is None:
            raise SisabError("Could not find Procedimento filter select.")
        procedimentos = [
            option["value"]
            for option in procedimento_select.find_all("option")
            if option.get("value")
        ]
        if not procedimentos:
            raise SisabError("SISAB returned no Procedimento filter options.")

        client.form = JsForm(
            action=urljoin(BASE_URL, form.get("action", REPORT_PATH)),
            view_state=view_state,
            competencia_name=competencia_select["name"],
            competencias={
                option["value"]
                for option in competencia_select.find_all("option")
                if option.get("value")
            },
            csv_button_name=client._csv_button_name_from_soup(form),
        )
        return ReportForm(client=client, procedimentos=procedimentos)
    except Exception:
        client.close()
        raise


def parse_sisab_csv(text: str, competencia: str) -> list[dict[str, object]]:
    lines = [line for line in text.splitlines() if line.strip()]
    header_index = next(
        (
            index
            for index, line in enumerate(lines)
            if line.lstrip("\ufeff").startswith("Uf;Ibge;Municipio;")
        ),
        None,
    )
    if header_index is None:
        raise SisabError("Could not find the Uf;Ibge;Municipio CSV header.")

    rows = csv.DictReader(lines[header_index:], delimiter=";")
    tidy: list[dict[str, object]] = []
    for row in rows:
        uf = (row.get("Uf") or "").strip()
        ibge = (row.get("Ibge") or "").strip()
        municipio = (row.get("Municipio") or "").strip()
        if not uf or not ibge or not municipio:
            continue

        for column, value in row.items():
            if column in {"Uf", "Ibge", "Municipio"} or column is None or not column.strip():
                continue
            tidy.append(
                {
                    "competencia": competencia,
                    "uf": uf,
                    "ibge": ibge,
                    "municipio": municipio,
                    "procedimento": column.strip(),
                    "valor": parse_br_integer(value),
                }
            )
    return tidy


def validate_rows(
    rows: list[dict[str, object]],
    competencia: str,
) -> None:
    if not rows:
        raise SisabError(f"SISAB returned no data rows for {competencia}.")
    for row in rows:
        if row["competencia"] != competencia:
            raise SisabError(f"Unexpected competencia in parsed row: {row['competencia']!r}.")
        if not row["uf"]:
            raise SisabError(f"Unexpected empty UF in parsed row for municipality {row['ibge']!r}.")


def sort_tidy_rows(rows: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(
        rows,
        key=lambda row: (
            str(row["competencia"]),
            str(row["uf"]),
            str(row["ibge"]),
            str(row["procedimento"]),
        ),
    )


def write_tidy_csv(path: Path, rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    with temp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=TIDY_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temp_path, path)


def default_output_path(output_dir: Path, competencia: str) -> Path:
    return output_dir / f"sisab_saude_procedimento_{competencia}.csv"


def read_or_download_brazil_csv(
    args: argparse.Namespace,
    report: ReportForm,
    competencia: str,
) -> list[dict[str, object]]:
    cache_path = raw_cache_path(args.raw_dir, competencia)
    invalid_cache = False
    if cache_path.exists() and not args.no_resume:
        LOGGER.info("%s: using cached raw CSV %s", competencia, cache_path)
        csv_text = cache_path.read_text(encoding="ISO-8859-1")
        try:
            rows = parse_sisab_csv(csv_text, competencia)
            validate_rows(rows, competencia)
            return rows
        except SisabError as error:
            invalid_cache = True
            LOGGER.warning("%s: cached raw CSV failed validation; redownloading: %s", competencia, error)

    last_error: Exception | None = None
    for attempt in range(1, args.retries + 2):
        try:
            csv_text = report.client.download_csv(
                competencia,
                COLUMN_PROCEDIMENTO,
                [(PROCEDIMENTO_SELECT_ID, procedimento) for procedimento in report.procedimentos],
                TP_PRODUCAO_PROCEDIMENTO,
            )
            rows = parse_sisab_csv(csv_text, competencia)
            validate_rows(rows, competencia)
            if not args.no_raw_cache:
                with cache_lock(cache_path, args.lock_timeout):
                    if invalid_cache or not cache_path.exists():
                        write_text_atomic(cache_path, csv_text, encoding="ISO-8859-1")
            return rows
        except (requests.RequestException, SisabError) as error:
            last_error = error
            if attempt <= args.retries:
                LOGGER.warning(
                    "%s: CSV validation/download failed (%d/%d); retrying: %s",
                    competencia,
                    attempt,
                    args.retries + 1,
                    error,
                )
                report.client.close()
                report = open_report(args)
                report.client._retry_sleep(attempt)
    raise last_error or SisabError("SISAB CSV failed without an exception.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scrape SISAB Saude Producao with Procedimento as report columns."
    )
    parser.add_argument(
        "--competencia",
        required=True,
        nargs="+",
        type=valid_competencia,
        metavar="YYYYMM",
        help="One competencia or start/end pair, e.g. 202604 or 202601 202604.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--retries", type=int, default=10)
    parser.add_argument("--retry-backoff", type=float, default=5.0)
    parser.add_argument("--retry-backoff-max", type=float, default=300.0)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw/sisab_saude_procedimento"))
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--no-raw-cache", action="store_true")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--json-log", action="store_true")
    parser.add_argument("--lock-timeout", type=float, default=3600.0)
    return parser


def configure_logging(level: str, json_log: bool = False) -> None:
    handler = logging.StreamHandler()
    if json_log:
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
    logging.basicConfig(level=getattr(logging, level), handlers=[handler], force=True)


def run_competencia(args: argparse.Namespace, competencia: str) -> list[Path]:
    report = open_report(args)
    try:
        started = time.monotonic()
        LOGGER.info("%s: downloading Brazil CSV", competencia)
        rows = read_or_download_brazil_csv(args, report, competencia)
        LOGGER.info("%s: parsed %d tidy rows in %.1fs", competencia, len(rows), time.monotonic() - started)
    finally:
        report.client.close()

    output = default_output_path(args.output_dir, competencia)
    write_tidy_csv(output, sort_tidy_rows(rows))
    LOGGER.info("%s: wrote %d tidy rows to %s", competencia, len(rows), output)
    return [output]


def run(args: argparse.Namespace) -> list[Path]:
    competencias = expand_competencias(args.competencia)

    discovery = open_report(args)
    try:
        form = discovery.client._require_form()
        missing_competencias = [item for item in competencias if item not in form.competencias]
        if missing_competencias:
            available = ", ".join(sorted(form.competencias, reverse=True)[:12])
            raise SisabError(
                f"Competencia(s) not available on SISAB: {', '.join(missing_competencias)}. "
                f"Recent available values: {available}"
            )
    finally:
        discovery.client.close()

    outputs: list[Path] = []
    for competencia in competencias:
        outputs.extend(run_competencia(args, competencia))
    return outputs


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    configure_logging(args.log_level, args.json_log)
    try:
        outputs = run(args)
    except (requests.RequestException, SisabError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    for output in outputs:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
