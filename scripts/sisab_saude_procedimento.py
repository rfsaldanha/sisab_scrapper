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
    CSV_BUTTON,
    LINE_MUNICIPIO,
    REPORT_PATH,
    REPORT_URL,
    JsForm,
    JsonLogFormatter,
    MissingMunicipalityRowsError,
    SisabClient,
    SisabError,
    State,
    cache_lock,
    chunk_cache_path,
    chunks,
    expand_competencias,
    filter_states,
    parse_br_integer,
    state_output_label,
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
    )
    return ReportForm(client=client, procedimentos=procedimentos)


def prepare_state_client(args: argparse.Namespace, state: State) -> ReportForm:
    report = open_report(args)
    report.client.select_municipio_geo()
    report.client.select_state(state)
    return report


def download_csv(
    client: SisabClient,
    competencia: str,
    state: State,
    municipios: list[str],
    procedimentos: list[str],
) -> str:
    form = client._require_form()
    base_payload = [
        (name, value)
        for name, value in client._base_payload(form.view_state)
        if name != "tpProducao"
    ]
    payload = (
        base_payload
        + [
            ("unidGeo", "municipio"),
            ("estadoMunicipio", state.code),
            (form.competencia_name, competencia),
            ("selectLinha", LINE_MUNICIPIO),
            ("selectcoluna", COLUMN_PROCEDIMENTO),
            ("idadeInicio", "0"),
            ("idadeFim", "0"),
            ("tpIdade", ""),
            ("tpProducao", TP_PRODUCAO_PROCEDIMENTO),
            (CSV_BUTTON, CSV_BUTTON),
        ]
        + [("municipios", municipio) for municipio in municipios]
        + [(PROCEDIMENTO_SELECT_ID, procedimento) for procedimento in procedimentos]
    )

    last_error: SisabError | None = None
    for attempt in range(1, client.retries + 2):
        response = client._request("POST", form.action, data=payload)
        content_type = response.headers.get("content-type", "")
        if "text/csv" in content_type.lower():
            response.encoding = response.encoding or "ISO-8859-1"
            return response.text

        preview = response.text[:500].replace("\n", " ")
        last_error = SisabError(
            f"SISAB did not return CSV for {state.uf}; content-type={content_type!r}; "
            f"preview={preview!r}"
        )
        if attempt <= client.retries:
            LOGGER.warning(
                "download failed (%d/%d); retrying: %s",
                attempt,
                client.retries + 1,
                last_error,
            )
            client._retry_sleep(attempt)
    raise last_error or SisabError("SISAB did not return CSV.")


def parse_sisab_csv(text: str, competencia: str, requested_uf: str) -> list[dict[str, object]]:
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
        if uf != requested_uf:
            raise SisabError(f"Expected UF {requested_uf}, got {uf} in CSV row for {municipio}.")

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
    expected_municipios: set[str],
    state: State,
    competencia: str,
    allow_missing_municipios: bool = False,
) -> None:
    if not rows:
        if allow_missing_municipios and expected_municipios:
            return
        raise MissingMunicipalityRowsError(f"SISAB returned no data rows for {state.uf} {competencia}.")

    seen_municipios = {str(row["ibge"]) for row in rows}
    missing = expected_municipios - seen_municipios
    if missing and not allow_missing_municipios:
        sample = ", ".join(sorted(missing)[:10])
        suffix = "..." if len(missing) > 10 else ""
        raise MissingMunicipalityRowsError(
            f"SISAB returned no rows for {len(missing)} requested municipalities "
            f"in {state.uf} {competencia}: {sample}{suffix}"
        )

    unexpected = seen_municipios - expected_municipios
    if unexpected:
        sample = ", ".join(sorted(unexpected)[:10])
        suffix = "..." if len(unexpected) > 10 else ""
        raise SisabError(
            f"SISAB returned rows for {len(unexpected)} unrequested municipalities "
            f"in {state.uf} {competencia}: {sample}{suffix}"
        )


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


def default_output_path(output_dir: Path, competencia: str, states: list[State]) -> Path:
    return output_dir / f"sisab_saude_procedimento_{competencia}_{state_output_label(states)}.csv"


def load_municipios_by_state(args: argparse.Namespace, states: list[State]) -> dict[str, list[str]]:
    municipios_by_state: dict[str, list[str]] = {}
    for index, state in enumerate(states, start=1):
        LOGGER.info("[%02d/%02d] %s: loading municipalities", index, len(states), state.uf)
        report = prepare_state_client(args, state)
        _, municipios = report.client.select_state(state)
        municipios_by_state[state.uf] = municipios
    return municipios_by_state


def read_or_download_chunk(
    args: argparse.Namespace,
    report: ReportForm,
    competencia: str,
    state: State,
    municipios: list[str],
) -> list[dict[str, object]]:
    cache_path = chunk_cache_path(args.raw_dir, competencia, state, municipios)
    expected_municipios = set(municipios)
    invalid_cache = False
    if cache_path.exists() and not args.no_resume:
        LOGGER.info("%s: using cached raw chunk %s", state.uf, cache_path)
        csv_text = cache_path.read_text(encoding="ISO-8859-1")
        try:
            rows = parse_sisab_csv(csv_text, competencia, state.uf)
            validate_rows(rows, expected_municipios, state, competencia, allow_missing_municipios=True)
            return rows
        except SisabError as error:
            invalid_cache = True
            LOGGER.warning("%s: cached raw chunk failed validation; redownloading: %s", state.uf, error)

    last_error: Exception | None = None
    missing_retry_used = False
    for attempt in range(1, args.retries + 2):
        try:
            csv_text = download_csv(report.client, competencia, state, municipios, report.procedimentos)
            rows = parse_sisab_csv(csv_text, competencia, state.uf)
            try:
                validate_rows(rows, expected_municipios, state, competencia)
            except MissingMunicipalityRowsError as error:
                if not missing_retry_used:
                    missing_retry_used = True
                    LOGGER.warning("%s: %s; retrying once to confirm zero-event municipalities", state.uf, error)
                    report = prepare_state_client(args, state)
                    report.client._retry_sleep(1)
                    continue
                LOGGER.warning("%s: accepting chunk with zero-row municipalities after confirmation: %s", state.uf, error)
                validate_rows(rows, expected_municipios, state, competencia, allow_missing_municipios=True)
            if not args.no_raw_cache:
                with cache_lock(cache_path, args.lock_timeout):
                    if invalid_cache or not cache_path.exists():
                        write_text_atomic(cache_path, csv_text, encoding="ISO-8859-1")
            return rows
        except (requests.RequestException, SisabError) as error:
            last_error = error
            if attempt <= args.retries:
                LOGGER.warning(
                    "%s: chunk validation/download failed (%d/%d); retrying: %s",
                    state.uf,
                    attempt,
                    args.retries + 1,
                    error,
                )
                report = prepare_state_client(args, state)
                report.client._retry_sleep(attempt)

    if args.adaptive_chunks and len(municipios) > 1:
        report = prepare_state_client(args, state)
        midpoint = len(municipios) // 2
        LOGGER.warning(
            "%s: chunk with %d municipalities failed after retries; splitting into %d and %d",
            state.uf,
            len(municipios),
            midpoint,
            len(municipios) - midpoint,
        )
        return read_or_download_chunk(args, report, competencia, state, municipios[:midpoint]) + read_or_download_chunk(
            args, report, competencia, state, municipios[midpoint:]
        )
    raise last_error or SisabError("SISAB chunk failed without an exception.")


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
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Output tidy CSV path for single-competencia runs. "
            "Defaults to <output-dir>/sisab_saude_procedimento_<competencia>_<uf-label>.csv."
        ),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    parser.add_argument("--state", action="append", default=[])
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--retries", type=int, default=10)
    parser.add_argument("--retry-backoff", type=float, default=5.0)
    parser.add_argument("--retry-backoff-max", type=float, default=300.0)
    parser.add_argument("--municipality-chunk-size", type=int, default=10)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw/sisab_saude_procedimento"))
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--no-raw-cache", action="store_true")
    parser.add_argument("--adaptive-chunks", action=argparse.BooleanOptionalAction, default=True)
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


def run_competencia(
    args: argparse.Namespace,
    competencia: str,
    states: list[State],
    municipios_by_state: dict[str, list[str]],
) -> Path:
    output = args.output or default_output_path(args.output_dir, competencia, states)
    all_rows: list[dict[str, object]] = []

    for index, state in enumerate(states, start=1):
        LOGGER.info("%s [%02d/%02d] %s: opening state session", competencia, index, len(states), state.uf)
        report = prepare_state_client(args, state)
        municipios = municipios_by_state[state.uf]
        municipio_chunks = list(chunks(municipios, args.municipality_chunk_size))

        state_rows: list[dict[str, object]] = []
        for chunk_index, municipio_chunk in enumerate(municipio_chunks, start=1):
            started = time.monotonic()
            LOGGER.info(
                "%s [%02d/%02d] %s: chunk %d/%d (%d municipalities)",
                competencia,
                index,
                len(states),
                state.uf,
                chunk_index,
                len(municipio_chunks),
                len(municipio_chunk),
            )
            chunk_rows = read_or_download_chunk(args, report, competencia, state, municipio_chunk)
            LOGGER.info(
                "%s [%02d/%02d] %s: chunk %d/%d yielded %d tidy rows in %.1fs",
                competencia,
                index,
                len(states),
                state.uf,
                chunk_index,
                len(municipio_chunks),
                len(chunk_rows),
                time.monotonic() - started,
            )
            state_rows.extend(chunk_rows)

        validate_rows(state_rows, set(municipios), state, competencia, allow_missing_municipios=True)
        LOGGER.info("%s [%02d/%02d] %s: %d tidy rows", competencia, index, len(states), state.uf, len(state_rows))
        all_rows.extend(state_rows)

    write_tidy_csv(output, sort_tidy_rows(all_rows))
    return output


def run(args: argparse.Namespace) -> list[Path]:
    competencias = expand_competencias(args.competencia)
    if args.output and len(competencias) > 1:
        raise SisabError("--output can only be used when scraping a single competencia.")

    discovery = open_report(args)
    form = discovery.client._require_form()
    missing_competencias = [item for item in competencias if item not in form.competencias]
    if missing_competencias:
        available = ", ".join(sorted(form.competencias, reverse=True)[:12])
        raise SisabError(
            f"Competencia(s) not available on SISAB: {', '.join(missing_competencias)}. "
            f"Recent available values: {available}"
        )
    _, states = discovery.client.select_municipio_geo()
    states = filter_states(states, args.state)
    municipios_by_state = load_municipios_by_state(args, states)

    return [run_competencia(args, competencia, states, municipios_by_state) for competencia in competencias]


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
