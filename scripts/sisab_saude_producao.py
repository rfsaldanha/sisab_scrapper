#!/usr/bin/env python3
"""Download SISAB Saude: Atendimento/Visita production data as tidy CSV."""

from __future__ import annotations

import argparse
import contextlib
import csv
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

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://sisab.saude.gov.br"
REPORT_PATH = "/paginas/acessoRestrito/relatorio/municipio/saude/RelSauProducao.xhtml"
REPORT_URL = urljoin(BASE_URL, REPORT_PATH)

LINE_MUNICIPIO = "MUN.CO_MUNICIPIO_IBGE"
COLUMN_TIPO_PRODUCAO = "CO_TIPO_FICHA_ATENDIMENTO"
USER_AGENT = "sisab-scrapper/0.1 (+https://sisab.saude.gov.br/)"
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
class JsForm:
    action: str
    view_state: str
    competencia_name: str
    competencias: set[str]
    csv_button_name: str


class SisabError(RuntimeError):
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
        csv_button_name = self._csv_button_name_from_soup(form)
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
            csv_button_name=csv_button_name,
        )
        return self.form

    def download_csv(
        self,
        competencia: str,
        column: str = COLUMN_TIPO_PRODUCAO,
        extra_filters: list[tuple[str, str]] | None = None,
        tipo_producao: str = "",
    ) -> str:
        form = self._require_form()
        # The CSV download is a normal JSF form post with the hidden CSV button id.
        base_payload = [(name, value) for name, value in self._base_payload(form.view_state) if name != "tpProducao"]
        payload = (
            base_payload
            + [
                (form.competencia_name, competencia),
                ("selectLinha", LINE_MUNICIPIO),
                ("selectcoluna", column),
                ("idadeInicio", "0"),
                ("idadeFim", "0"),
                ("tpIdade", ""),
                ("tpProducao", tipo_producao),
                (form.csv_button_name, form.csv_button_name),
            ]
            + (extra_filters or [])
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
                f"SISAB did not return CSV for {competencia}; content-type={content_type!r}; preview={preview!r}"
            )
            if attempt <= self.retries:
                LOGGER.warning(
                    f"download failed ({attempt}/{self.retries + 1}); retrying: {last_error}",
                )
                self._retry_sleep(attempt)
        raise last_error or SisabError("SISAB did not return CSV.")

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
    def _csv_button_name_from_soup(form) -> str:
        for link in form.find_all("a"):
            if link.get_text(strip=True).lower() != "csv":
                continue
            match = re.search(r"\{'([^']+)':'\1'\}", link.get("onclick", ""))
            if match:
                return match.group(1)
        raise SisabError("Could not find the SISAB CSV download link.")


def parse_sisab_csv(text: str, competencia: str) -> list[dict[str, object]]:
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
    competencia: str,
) -> None:
    if not rows:
        raise SisabError(f"SISAB returned no data rows for {competencia}.")

    by_municipio: dict[str, set[str]] = {}
    for row in rows:
        if row["competencia"] != competencia:
            raise SisabError(f"Unexpected competencia in parsed row: {row['competencia']!r}.")
        if not row["uf"]:
            raise SisabError(f"Unexpected empty UF in parsed row for municipality {row['ibge']!r}.")
        by_municipio.setdefault(str(row["ibge"]), set()).add(str(row["tipo_producao"]))

    incomplete = {
        ibge: EXPECTED_TIPO_PRODUCAO - tipo_producao
        for ibge, tipo_producao in by_municipio.items()
        if tipo_producao != EXPECTED_TIPO_PRODUCAO
    }
    if incomplete:
        ibge, missing_tipo = next(iter(sorted(incomplete.items())))
        raise SisabError(
            f"Incomplete production categories for municipality {ibge}: missing {', '.join(sorted(missing_tipo))}."
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


def raw_cache_path(cache_dir: Path, competencia: str) -> Path:
    return cache_dir / competencia / "brasil.csv"


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


def new_client(args: argparse.Namespace) -> SisabClient:
    return SisabClient(
        delay=args.delay,
        timeout=args.timeout,
        retries=args.retries,
        retry_backoff=args.retry_backoff,
        retry_backoff_max=args.retry_backoff_max,
    )


def open_client(args: argparse.Namespace) -> SisabClient:
    client = SisabClient(
        delay=args.delay,
        timeout=args.timeout,
        retries=args.retries,
        retry_backoff=args.retry_backoff,
        retry_backoff_max=args.retry_backoff_max,
    )
    try:
        client.open_report()
        return client
    except Exception:
        client.close()
        raise


def read_or_download_brazil_csv(
    args: argparse.Namespace,
    client: SisabClient,
    competencia: str,
    column: str = COLUMN_TIPO_PRODUCAO,
    extra_filters: list[tuple[str, str]] | None = None,
    tipo_producao: str = "",
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
            csv_text = client.download_csv(competencia, column, extra_filters, tipo_producao)
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
                client.close()
                client = open_client(args)
                client._retry_sleep(attempt)
    raise last_error or SisabError("SISAB CSV failed without an exception.")


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
        "--output-dir",
        type=Path,
        default=Path("data"),
        help="Directory for default output CSVs. Default: data.",
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
        "--raw-dir",
        type=Path,
        default=Path("data/raw/sisab_saude_producao"),
        help="Directory for raw SISAB Brazil CSV cache. Default: data/raw/sisab_saude_producao.",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore cached raw CSVs and download everything again.",
    )
    parser.add_argument(
        "--no-raw-cache",
        action="store_true",
        help="Do not save downloaded raw SISAB CSVs.",
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


def default_output_path(output_dir: Path, competencia: str) -> Path:
    return output_dir / f"sisab_saude_producao_{competencia}.csv"


def run_competencia(args: argparse.Namespace, competencia: str) -> list[Path]:
    client = open_client(args)
    try:
        started = time.monotonic()
        LOGGER.info("%s: downloading Brazil CSV", competencia)
        rows = read_or_download_brazil_csv(args, client, competencia)
        LOGGER.info("%s: parsed %d tidy rows in %.1fs", competencia, len(rows), time.monotonic() - started)
    finally:
        client.close()

    output = default_output_path(args.output_dir, competencia)
    write_tidy_csv(output, sort_tidy_rows(rows))
    LOGGER.info("%s: wrote %d tidy rows to %s", competencia, len(rows), output)
    return [output]


def run(args: argparse.Namespace) -> list[Path]:
    competencias = expand_competencias(args.competencia)
    discovery = open_client(args)
    try:
        form = discovery._require_form()
        missing_competencias = [item for item in competencias if item not in form.competencias]
        if missing_competencias:
            available = ", ".join(sorted(form.competencias, reverse=True)[:12])
            raise SisabError(
                f"Competencia(s) not available on SISAB: {', '.join(missing_competencias)}. "
                f"Recent available values: {available}"
            )
    finally:
        discovery.close()

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
