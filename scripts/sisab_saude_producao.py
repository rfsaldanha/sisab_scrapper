#!/usr/bin/env python3
"""Download SISAB Saude: Atendimento/Visita production data as tidy CSV."""

from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import json
import logging
import os
import random
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator
from urllib.parse import urljoin
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://sisab.saude.gov.br"
REPORT_PATH = "/paginas/acessoRestrito/relatorio/federal/saude/RelSauProducao.xhtml"
REPORT_URL = urljoin(BASE_URL, REPORT_PATH)

LINE_MUNICIPIO = "MUN.CO_MUNICIPIO_IBGE"
COLUMN_TIPO_PRODUCAO = "CO_TIPO_FICHA_ATENDIMENTO"
CSV_BUTTON = "j_idt192"
USER_AGENT = "sisab-scrapper/0.1 (+https://sisab.saude.gov.br/)"
MUNICIPALITY_CACHE_VERSION = 1
DEFAULT_MUNICIPALITY_CACHE = Path("data/raw/sisab_municipios.json")
EXPECTED_TIPO_PRODUCAO = {
    "Atendimento Individual",
    "Atendimento Odontológico",
    "Procedimento",
    "Visita Domiciliar",
}
LOGGER = logging.getLogger("sisab_saude_producao")
TIDY_FIELDNAMES = [
    "competencia",
    "uf",
    "ibge",
    "municipio",
    "tipo_producao",
    "valor",
]


@dataclass(frozen=True)
class State:
    code: str
    uf: str


@dataclass(frozen=True)
class JsForm:
    action: str
    view_state: str
    competencia_name: str
    competencias: set[str]


class SisabError(RuntimeError):
    pass


class MissingMunicipalityRowsError(SisabError):
    pass


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        return json.dumps(payload, ensure_ascii=False)


class SisabClient:
    """Small JSF client for the SISAB report form."""

    def __init__(
        self,
        delay: float,
        timeout: float,
        retries: int,
        retry_backoff: float,
        retry_backoff_max: float,
    ) -> None:
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.retry_backoff = retry_backoff
        self.retry_backoff_max = retry_backoff_max
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.form: JsForm | None = None

    def close(self) -> None:
        self.session.close()

    def _sleep(self) -> None:
        if self.delay > 0:
            time.sleep(self.delay)

    def _retry_sleep(self, attempt: int) -> None:
        if self.retry_backoff <= 0:
            return
        # Jitter keeps repeated retries from landing on the same server rhythm.
        backoff = min(self.retry_backoff_max, self.retry_backoff * (2 ** (attempt - 1)))
        time.sleep(backoff + random.uniform(0, min(1.0, backoff * 0.1)))

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 2):
            try:
                self._sleep()
                response = self.session.request(method, url, timeout=self.timeout, **kwargs)
                response.raise_for_status()
                return response
            except requests.RequestException as error:
                last_error = error
                if attempt > self.retries:
                    break
                LOGGER.warning(
                    f"request failed ({attempt}/{self.retries + 1}); retrying: {error}",
                )
                self._retry_sleep(attempt)
        raise last_error or SisabError("Request failed without an exception.")

    def open_report(self) -> JsForm:
        response = self._request("GET", REPORT_URL)
        soup = BeautifulSoup(response.text, "html.parser")
        # The public report is a JavaServer Faces form; ViewState and dynamic
        # field names must come from the page on each session.
        form = soup.find("form", id="j_idt44")
        if form is None:
            raise SisabError("Could not find SISAB report form j_idt44.")

        view_state = self._view_state_from_soup(form)
        competencia = form.find("span", id="competencia")
        competencia_select = competencia.find("select", attrs={"name": True}) if competencia else None
        if competencia_select is None:
            raise SisabError("Could not find competencia select field.")

        action = urljoin(BASE_URL, form.get("action", REPORT_PATH))
        competencias = {
            option["value"]
            for option in competencia_select.find_all("option")
            if option.get("value")
        }
        self.form = JsForm(
            action=action,
            view_state=view_state,
            competencia_name=competencia_select["name"],
            competencias=competencias,
        )
        return self.form

    def select_municipio_geo(self) -> tuple[str, list[State]]:
        form = self._require_form()
        # Mimic the UI AJAX event that reveals the Estado and Municipios fields.
        response = self._partial_post(
            source="unidGeo",
            execute="unidGeo",
            render="regioes script",
            data=self._base_payload(form.view_state) + [("unidGeo", "municipio")],
        )
        updates = self._parse_partial_response(response.text)
        self._set_view_state(updates)
        regioes = updates.get("regioes", "")
        soup = BeautifulSoup(regioes, "html.parser")
        state_select = soup.find("select", id="estadoMunicipio")
        if state_select is None:
            raise SisabError("Could not load the Estado select after choosing Municipios.")
        states = [
            State(code=option["value"], uf=option.get_text(strip=True))
            for option in state_select.find_all("option")
            if option.get("value")
        ]
        return self._require_form().view_state, states

    def select_state(self, state: State) -> tuple[str, list[str]]:
        form = self._require_form()
        # Selecting a UF via AJAX populates the municipality multi-select.
        response = self._partial_post(
            source="estadoMunicipio",
            execute="estadoMunicipio",
            render="regioes script",
            data=self._base_payload(form.view_state)
            + [
                ("unidGeo", "municipio"),
                ("estadoMunicipio", state.code),
            ],
        )
        updates = self._parse_partial_response(response.text)
        self._set_view_state(updates)
        regioes = updates.get("regioes", "")
        soup = BeautifulSoup(regioes, "html.parser")
        municipio_select = soup.find("select", id="municipios")
        if municipio_select is None:
            raise SisabError(f"Could not load municipality list for {state.uf}.")
        municipios = [
            option["value"]
            for option in municipio_select.find_all("option")
            if option.get("value")
        ]
        if not municipios:
            raise SisabError(f"SISAB returned no municipalities for {state.uf}.")
        return self._require_form().view_state, municipios

    def download_csv(self, competencia: str, state: State, municipios: list[str]) -> str:
        form = self._require_form()
        # The CSV download is a normal JSF form post with the hidden CSV button id.
        payload = (
            self._base_payload(form.view_state)
            + [
                ("unidGeo", "municipio"),
                ("estadoMunicipio", state.code),
                (form.competencia_name, competencia),
                ("selectLinha", LINE_MUNICIPIO),
                ("selectcoluna", COLUMN_TIPO_PRODUCAO),
                ("idadeInicio", "0"),
                ("idadeFim", "0"),
                ("tpIdade", ""),
                ("tpProducao", ""),
                (CSV_BUTTON, CSV_BUTTON),
            ]
            + [("municipios", municipio) for municipio in municipios]
        )
        last_error: SisabError | None = None
        for attempt in range(1, self.retries + 2):
            response = self._request("POST", form.action, data=payload)
            content_type = response.headers.get("content-type", "")
            if "text/csv" in content_type.lower():
                response.encoding = response.encoding or "ISO-8859-1"
                return response.text

            preview = response.text[:500].replace("\n", " ")
            last_error = SisabError(
                f"SISAB did not return CSV for {state.uf}; content-type={content_type!r}; "
                f"preview={preview!r}"
            )
            if attempt <= self.retries:
                LOGGER.warning(
                    f"download failed ({attempt}/{self.retries + 1}); retrying: {last_error}",
                )
                self._retry_sleep(attempt)
        raise last_error or SisabError("SISAB did not return CSV.")

    def _partial_post(
        self,
        source: str,
        execute: str,
        render: str,
        data: list[tuple[str, str]],
    ) -> requests.Response:
        form = self._require_form()
        payload = data + [
            ("javax.faces.partial.ajax", "true"),
            ("javax.faces.source", source),
            ("javax.faces.partial.execute", execute),
            ("javax.faces.partial.render", render),
            ("javax.faces.behavior.event", "valueChange"),
            ("javax.faces.partial.event", "change"),
        ]
        return self._request(
            "POST",
            form.action,
            data=payload,
            headers={"Faces-Request": "partial/ajax"},
        )

    def _base_payload(self, view_state: str) -> list[tuple[str, str]]:
        return [
            ("j_idt44", "j_idt44"),
            ("lsCid", ""),
            ("lsSigtap", ""),
            ("idadeInicio", "0"),
            ("idadeFim", "0"),
            ("tpIdade", ""),
            ("tpProducao", ""),
            ("javax.faces.ViewState", view_state),
        ]

    def _set_view_state(self, updates: dict[str, str]) -> None:
        form = self._require_form()
        view_state = updates.get("javax.faces.ViewState")
        if not view_state:
            raise SisabError("SISAB partial response did not include a new ViewState.")
        # JSF invalidates old ViewState values after partial updates.
        self.form = JsForm(
            action=form.action,
            view_state=view_state,
            competencia_name=form.competencia_name,
            competencias=form.competencias,
        )

    def _require_form(self) -> JsForm:
        if self.form is None:
            raise SisabError("Report form has not been opened yet.")
        return self.form

    @staticmethod
    def _view_state_from_soup(form) -> str:
        field = form.find("input", attrs={"name": "javax.faces.ViewState"})
        if field is None or not field.get("value"):
            raise SisabError("Could not find javax.faces.ViewState.")
        return field["value"]

    @staticmethod
    def _parse_partial_response(text: str) -> dict[str, str]:
        root = ElementTree.fromstring(text)
        updates: dict[str, str] = {}
        for update in root.iter("update"):
            update_id = update.attrib.get("id")
            if update_id:
                updates[update_id] = update.text or ""
        return updates


def parse_sisab_csv(text: str, competencia: str, requested_uf: str) -> list[dict[str, object]]:
    lines = [line for line in text.splitlines() if line.strip()]
    # SISAB prepends metadata before the semicolon-delimited table.
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
            # A trailing semicolon creates an empty DictReader column; ignore it.
            if column in {"Uf", "Ibge", "Municipio"} or column is None or not column.strip():
                continue
            tidy.append(
                {
                    "competencia": competencia,
                    "uf": uf,
                    "ibge": ibge,
                    "municipio": municipio,
                    "tipo_producao": column.strip(),
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

    by_municipio: dict[str, set[str]] = {}
    for row in rows:
        if row["competencia"] != competencia:
            raise SisabError(f"Unexpected competencia in parsed row: {row['competencia']!r}.")
        if row["uf"] != state.uf:
            raise SisabError(f"Unexpected UF in parsed row: {row['uf']!r}; expected {state.uf}.")
        by_municipio.setdefault(str(row["ibge"]), set()).add(str(row["tipo_producao"]))

    incomplete = {
        ibge: EXPECTED_TIPO_PRODUCAO - tipo_producao
        for ibge, tipo_producao in by_municipio.items()
        if tipo_producao != EXPECTED_TIPO_PRODUCAO
    }
    if incomplete:
        ibge, missing_tipo = next(iter(sorted(incomplete.items())))
        raise SisabError(
            f"Incomplete production categories for {state.uf} municipality {ibge}: "
            f"missing {', '.join(sorted(missing_tipo))}."
        )


def parse_br_integer(value: str | None) -> int:
    if value is None:
        return 0
    value = value.strip()
    if not value or value == "-":
        return 0
    return int(value.replace(".", ""))


def write_tidy_csv(path: Path, rows: Iterable[dict[str, object]]) -> None:
    # Atomic replace prevents a partial final CSV if the process dies mid-write.
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    with temp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=TIDY_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temp_path, path)


def write_text_atomic(path: Path, text: str, encoding: str = "ISO-8859-1") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(text, encoding=encoding)
    os.replace(temp_path, path)


def chunks(values: list[str], size: int) -> Iterable[list[str]]:
    if size < 1:
        raise ValueError("Municipality chunk size must be at least 1.")
    for start in range(0, len(values), size):
        yield values[start : start + size]


def sort_tidy_rows(rows: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(
        rows,
        key=lambda row: (
            str(row["competencia"]),
            str(row["uf"]),
            str(row["ibge"]),
            str(row["tipo_producao"]),
        ),
    )


def chunk_cache_path(cache_dir: Path, competencia: str, state: State, municipios: list[str]) -> Path:
    joined = ",".join(municipios)
    # Include a hash so adaptive chunks with similar boundaries cannot collide.
    digest = hashlib.sha1(joined.encode("ascii")).hexdigest()[:12]
    first = municipios[0]
    last = municipios[-1]
    name = f"{state.uf}_{first}_{last}_{len(municipios)}_{digest}.csv"
    return cache_dir / competencia / state.uf / name


@contextlib.contextmanager
def cache_lock(path: Path, timeout: float, poll_interval: float = 1.0) -> Iterator[None]:
    lock_path = path.with_name(f".{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    fd: int | None = None
    while fd is None:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("ascii"))
        except FileExistsError:
            if time.monotonic() - started > timeout:
                raise SisabError(f"Timed out waiting for cache lock {lock_path}.")
            time.sleep(poll_interval)
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
        with contextlib.suppress(FileNotFoundError):
            lock_path.unlink()


def prepare_state_client(args: argparse.Namespace, state: State) -> SisabClient:
    client = SisabClient(
        delay=args.delay,
        timeout=args.timeout,
        retries=args.retries,
        retry_backoff=args.retry_backoff,
        retry_backoff_max=args.retry_backoff_max,
    )
    try:
        client.open_report()
        client.select_municipio_geo()
        client.select_state(state)
        return client
    except Exception:
        client.close()
        raise


def read_or_download_chunk(
    args: argparse.Namespace,
    client: SisabClient,
    competencia: str,
    state: State,
    municipios: list[str],
) -> list[dict[str, object]]:
    cache_path = chunk_cache_path(args.raw_dir, competencia, state, municipios)
    expected_municipios = set(municipios)
    invalid_cache = False
    if cache_path.exists() and not args.no_resume:
        # Cached raw chunks are revalidated before reuse.
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
            csv_text = client.download_csv(competencia, state, municipios)
            rows = parse_sisab_csv(csv_text, competencia, state.uf)
            try:
                validate_rows(rows, expected_municipios, state, competencia)
            except MissingMunicipalityRowsError as error:
                if not missing_retry_used:
                    missing_retry_used = True
                    LOGGER.warning("%s: %s; retrying once to confirm zero-event municipalities", state.uf, error)
                    client = prepare_state_client(args, state)
                    client._retry_sleep(1)
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
                client = prepare_state_client(args, state)
                client._retry_sleep(attempt)

    # Large municipality selections can time out or return incomplete CSVs; split smaller.
    if args.adaptive_chunks and len(municipios) > 1:
        client = prepare_state_client(args, state)
        midpoint = len(municipios) // 2
        LOGGER.warning(
            "%s: chunk with %d municipalities failed after retries; splitting into %d and %d",
            state.uf,
            len(municipios),
            midpoint,
            len(municipios) - midpoint,
        )
        return read_or_download_chunk(args, client, competencia, state, municipios[:midpoint]) + read_or_download_chunk(
            args, client, competencia, state, municipios[midpoint:]
        )
    raise last_error or SisabError("SISAB chunk failed without an exception.")


def filter_states(states: list[State], wanted: list[str]) -> list[State]:
    if not wanted:
        return states
    wanted_upper = {item.upper() for item in wanted}
    selected = [
        state
        for state in states
        if state.uf.upper() in wanted_upper or state.code in wanted_upper
    ]
    missing = wanted_upper - {state.uf.upper() for state in selected} - {state.code for state in selected}
    if missing:
        raise SisabError(f"Unknown state(s): {', '.join(sorted(missing))}")
    return selected


def valid_competencia(value: str) -> str:
    if not re.fullmatch(r"\d{6}", value):
        raise argparse.ArgumentTypeError("Competencia must use YYYYMM, for example 202604.")
    month = int(value[4:6])
    if month < 1 or month > 12:
        raise argparse.ArgumentTypeError("Competencia month must be between 01 and 12.")
    return value


def competencia_to_month_index(value: str) -> int:
    return int(value[:4]) * 12 + int(value[4:6]) - 1


def month_index_to_competencia(index: int) -> str:
    year = index // 12
    month = index % 12 + 1
    return f"{year:04d}{month:02d}"


def expand_competencias(values: list[str]) -> list[str]:
    if len(values) == 1:
        return values
    if len(values) != 2:
        raise argparse.ArgumentTypeError("--competencia accepts one value or a start/end pair.")

    start, end = values
    # Convert YYYYMM to a linear month number to handle year boundaries.
    start_index = competencia_to_month_index(start)
    end_index = competencia_to_month_index(end)
    if start_index > end_index:
        raise argparse.ArgumentTypeError("Competencia start must be earlier than or equal to end.")
    return [month_index_to_competencia(index) for index in range(start_index, end_index + 1)]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scrape SISAB Saude Producao for one competencia or an inclusive range."
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
            "Output tidy CSV path. Only valid when scraping exactly one competencia and one state. "
            "Defaults to <output-dir>/sisab_saude_producao_<competencia>_<uf>.csv."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data"),
        help="Directory for default output CSVs. Default: data.",
    )
    parser.add_argument(
        "--state",
        action="append",
        default=[],
        help="Optional UF or UF IBGE code to limit the run. Repeat for multiple states.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Seconds to wait before every HTTP request. Default: 2.0.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=900.0,
        help="HTTP timeout in seconds. Default: 900.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=10,
        help="Retries per failed HTTP/download request before aborting. Default: 10.",
    )
    parser.add_argument(
        "--retry-backoff",
        type=float,
        default=5.0,
        help="Initial retry backoff in seconds. Default: 5.",
    )
    parser.add_argument(
        "--retry-backoff-max",
        type=float,
        default=300.0,
        help="Maximum retry backoff in seconds. Default: 300.",
    )
    parser.add_argument(
        "--municipality-chunk-size",
        type=int,
        default=10,
        help=(
            "Maximum municipalities selected in one SISAB download request. "
            "Default: 10, which avoids server errors/timeouts for large UFs."
        ),
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path("data/raw/sisab_saude_producao"),
        help="Directory for raw SISAB chunk CSV cache. Default: data/raw/sisab_saude_producao.",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore cached raw chunks and download everything again.",
    )
    parser.add_argument(
        "--no-raw-cache",
        action="store_true",
        help="Do not save downloaded raw SISAB chunks.",
    )
    parser.add_argument(
        "--municipality-cache",
        type=Path,
        default=DEFAULT_MUNICIPALITY_CACHE,
        help=f"Path for the shared municipality-list cache. Default: {DEFAULT_MUNICIPALITY_CACHE}.",
    )
    parser.add_argument(
        "--refresh-municipality-cache",
        action="store_true",
        help="Reload municipality lists from SISAB and update the shared cache.",
    )
    parser.add_argument(
        "--adaptive-chunks",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Split a failed chunk into smaller chunks after retries are exhausted. Default: enabled.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity. Default: INFO.",
    )
    parser.add_argument(
        "--json-log",
        action="store_true",
        help="Emit progress logs as JSON lines on stderr.",
    )
    parser.add_argument(
        "--lock-timeout",
        type=float,
        default=3600.0,
        help="Seconds to wait for raw cache write locks. Default: 3600.",
    )
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


def default_output_path(output_dir: Path, competencia: str, state: State) -> Path:
    return output_dir / f"sisab_saude_producao_{competencia}_{state.uf}.csv"


def read_municipality_cache(path: Path, states: list[State]) -> dict[str, list[str]] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        LOGGER.warning("could not read municipality cache %s; refreshing: %s", path, error)
        return None

    if payload.get("version") != MUNICIPALITY_CACHE_VERSION:
        LOGGER.warning("municipality cache %s has an unsupported version; refreshing", path)
        return None

    cached_states = {
        str(item.get("uf")): item
        for item in payload.get("states", [])
        if isinstance(item, dict) and item.get("uf")
    }
    municipios_by_state: dict[str, list[str]] = {}
    for state in states:
        item = cached_states.get(state.uf)
        if not item or item.get("code") != state.code:
            return None
        municipios = item.get("municipios")
        if not isinstance(municipios, list) or not municipios or not all(isinstance(value, str) for value in municipios):
            return None
        municipios_by_state[state.uf] = municipios

    LOGGER.info("using municipality cache %s for %d UF(s)", path, len(states))
    return municipios_by_state


def write_municipality_cache(path: Path, states: list[State], municipios_by_state: dict[str, list[str]]) -> None:
    cached_by_uf: dict[str, dict[str, object]] = {}
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("version") == MUNICIPALITY_CACHE_VERSION:
                cached_by_uf = {
                    str(item.get("uf")): item
                    for item in payload.get("states", [])
                    if isinstance(item, dict) and item.get("uf")
                }
        except (OSError, json.JSONDecodeError):
            cached_by_uf = {}

    for state in states:
        cached_by_uf[state.uf] = {
            "code": state.code,
            "uf": state.uf,
            "municipios": municipios_by_state[state.uf],
        }

    payload = {
        "version": MUNICIPALITY_CACHE_VERSION,
        "states": sorted(cached_by_uf.values(), key=lambda item: str(item["uf"])),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp_path, path)


def load_municipios_by_state(args: argparse.Namespace, states: list[State]) -> dict[str, list[str]]:
    if not args.refresh_municipality_cache:
        cached = read_municipality_cache(args.municipality_cache, states)
        if cached is not None:
            return cached

    municipios_by_state: dict[str, list[str]] = {}
    for index, state in enumerate(states, start=1):
        LOGGER.info("[%02d/%02d] %s: loading municipalities", index, len(states), state.uf)
        client = SisabClient(
            delay=args.delay,
            timeout=args.timeout,
            retries=args.retries,
            retry_backoff=args.retry_backoff,
            retry_backoff_max=args.retry_backoff_max,
        )
        try:
            client.open_report()
            client.select_municipio_geo()
            _, municipios = client.select_state(state)
            municipios_by_state[state.uf] = municipios
        finally:
            client.close()
    write_municipality_cache(args.municipality_cache, states, municipios_by_state)
    return municipios_by_state


def run_competencia(
    args: argparse.Namespace,
    competencia: str,
    states: list[State],
    municipios_by_state: dict[str, list[str]],
) -> list[Path]:
    outputs: list[Path] = []
    for index, state in enumerate(states, start=1):
        LOGGER.info(
            "%s [%02d/%02d] %s: opening state session",
            competencia,
            index,
            len(states),
            state.uf,
        )
        municipios = municipios_by_state[state.uf]
        client = prepare_state_client(args, state)
        try:
            # Chunking keeps SISAB form submissions small enough for large UFs.
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
                chunk_rows = read_or_download_chunk(args, client, competencia, state, municipio_chunk)
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
        finally:
            client.close()

        validate_rows(state_rows, set(municipios), state, competencia, allow_missing_municipios=True)

        output = args.output or default_output_path(args.output_dir, competencia, state)
        write_tidy_csv(output, sort_tidy_rows(state_rows))
        outputs.append(output)
        LOGGER.info(
            "%s [%02d/%02d] %s: wrote %d tidy rows to %s",
            competencia,
            index,
            len(states),
            state.uf,
            len(state_rows),
            output,
        )
    return outputs


def run(args: argparse.Namespace) -> list[Path]:
    competencias = expand_competencias(args.competencia)

    # Discover available months and UFs once, then run each competencia separately.
    discovery = SisabClient(
        delay=args.delay,
        timeout=args.timeout,
        retries=args.retries,
        retry_backoff=args.retry_backoff,
        retry_backoff_max=args.retry_backoff_max,
    )
    try:
        discovery.open_report()
        form = discovery._require_form()
        missing_competencias = [item for item in competencias if item not in form.competencias]
        if missing_competencias:
            available = ", ".join(sorted(form.competencias, reverse=True)[:12])
            raise SisabError(
                f"Competencia(s) not available on SISAB: {', '.join(missing_competencias)}. "
                f"Recent available values: {available}"
            )
        _, states = discovery.select_municipio_geo()
    finally:
        discovery.close()
    states = filter_states(states, args.state)
    if args.output and (len(competencias) > 1 or len(states) > 1):
        raise SisabError("--output can only be used when scraping one competencia and one state.")
    municipios_by_state = load_municipios_by_state(args, states)

    outputs: list[Path] = []
    for competencia in competencias:
        outputs.extend(run_competencia(args, competencia, states, municipios_by_state))
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
