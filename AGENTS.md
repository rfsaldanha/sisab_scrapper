# AGENTS.md

Python scrapers for SISAB Saúde Produção. Main files: `scripts/sisab_saude_producao.py`, `scripts/sisab_saude_procedimento.py`, and `scripts/sisab_saude_condicao_avaliada.py`.

Fixed scrape config: `Municípios`; all UFs unless `--state`; all municipalities per UF; one `--competencia` or inclusive start/end pair; Linha `Municipio`; Coluna `Tipo de Produção`; no filters. Tidy output columns:

```text
competencia,uf,ibge,municipio,tipo_producao,valor
```

Procedimento scraper uses Coluna `Procedimento`, selects all `Procedimento` filter values, and outputs `competencia,uf,ibge,municipio,procedimento,valor`.

Condição Avaliada scraper uses Coluna `Probl/ Condição Avaliada`, selects all `Problema/Condição Avaliada` filter values, and outputs `competencia,uf,ibge,municipio,condicao_avaliada,valor`.

Preserve these rules:

- SISAB is slow/flaky: keep long timeouts, retries, backoff, delays, and adaptive chunks.
- Never write the final CSV until the full requested run succeeds; partial final output is useless.
- Competência ranges must write separate CSVs, one per month; `--output` is single-month only.
- Keep raw chunk cache/resume, cache locks, municipality caching, sorted final rows, and completeness validation unless explicitly removed.
- A repeated single-municipality failure should abort.
- Do not add derived columns unless requested.
- Do not commit generated outputs/caches: `data/`, `data/raw/sisab_saude_producao/`, `__pycache__/`, `*.pyc`.

Commands:

```bash
python3 -m unittest discover -s tests
python3 scripts/sisab_saude_producao.py --competencia 202604
python3 scripts/sisab_saude_producao.py --competencia 202601 202604
sisab-saude-producao --competencia 202604 --json-log
sisab-saude-procedimento --competencia 202604 --json-log
sisab-saude-condicao-avaliada --competencia 202604 --json-log
python3 scripts/sisab_saude_producao.py --competencia 202604 --state AC --output /tmp/sisab_ac.csv --raw-dir /tmp/sisab_raw_cache --delay 0.2 --timeout 300 --retries 1 --retry-backoff 0.2 --retry-backoff-max 1
```
