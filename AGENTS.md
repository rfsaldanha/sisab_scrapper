# AGENTS.md

SISAB Saúde Produção scrapers. Shared base: municipality-level report URL; all UFs and all municipalities in one request per scraper/competência; Linha `Municipio`; tidy CSV; one final CSV per competência.

Scripts/commands:

- `scripts/sisab_saude_producao.py` / `sisab-saude-producao`: Coluna `Tipo de Produção`; output `competencia,uf,ibge,municipio,tipo_producao,valor`.
- `scripts/sisab_saude_procedimento.py` / `sisab-saude-procedimento`: Coluna `Procedimento`; select all `Procedimento`; output `competencia,uf,ibge,municipio,procedimento,valor`.
- `scripts/sisab_saude_condicao_avaliada.py` / `sisab-saude-condicao-avaliada`: Coluna `Probl/ Condição Avaliada`; select all `Problema/Condição Avaliada`; output `competencia,uf,ibge,municipio,condicao_avaliada,valor`.

Preserve:

- SISAB is slow/flaky: keep long timeouts, retries, backoff, and delays.
- Revalidate cached raw Brazil CSVs before reuse; malformed cached CSVs must be redownloaded.
- Final CSVs are per competência and must be written atomically.
- Keep raw CSV cache/resume, cache locks, sorted final rows, and validation.
- Do not add derived columns unless requested.
- Do not commit generated outputs/caches: `data/`, `data/raw/sisab_saude_*`, `__pycache__/`, `*.pyc`.

Commands:

```bash
python3 -m unittest discover -s tests
python3 scripts/sisab_saude_producao.py --competencia 202604
python3 scripts/sisab_saude_procedimento.py --competencia 202604
python3 scripts/sisab_saude_condicao_avaliada.py --competencia 202604
sisab-saude-producao --competencia 202601 202604 --json-log
```
