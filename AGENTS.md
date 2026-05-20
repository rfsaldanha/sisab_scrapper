# AGENTS.md

Python scraper for SISAB Saúde Produção. Main file: `scripts/sisab_saude_producao.py`.

Fixed scrape config: `Municípios`; all UFs unless `--state`; all municipalities per UF; one `--competencia`; Linha `Municipio`; Coluna `Tipo de Produção`; no filters. Tidy output columns:

```text
competencia,uf,ibge,municipio,tipo_producao,valor
```

Preserve these rules:

- SISAB is slow/flaky: keep long timeouts, retries, backoff, delays, and adaptive chunks.
- Never write the final CSV until the full requested run succeeds; partial final output is useless.
- Keep raw chunk cache/resume and completeness validation unless explicitly removed.
- A repeated single-municipality failure should abort.
- Do not add derived columns unless requested.
- Do not commit generated outputs/caches: `data/`, `data/raw/sisab_saude_producao/`, `__pycache__/`, `*.pyc`.

Commands:

```bash
python3 -m unittest discover -s tests
python3 scripts/sisab_saude_producao.py --competencia 202604
python3 scripts/sisab_saude_producao.py --competencia 202604 --state AC --output /tmp/sisab_ac.csv --raw-dir /tmp/sisab_raw_cache --delay 0.2 --timeout 300 --retries 1 --retry-backoff 0.2 --retry-backoff-max 1
```
