# AGENTS.md

SISAB Saúde Produção scrapers. Shared base: `Municípios`; all UFs unless `--state`; all municipalities per UF; one `--competencia` or inclusive start/end pair; Linha `Municipio`; tidy CSV; one final CSV per competência.

Scripts/commands:

- `scripts/sisab_saude_producao.py` / `sisab-saude-producao`: Coluna `Tipo de Produção`; output `competencia,uf,ibge,municipio,tipo_producao,valor`.
- `scripts/sisab_saude_procedimento.py` / `sisab-saude-procedimento`: Coluna `Procedimento`; select all `Procedimento`; output `competencia,uf,ibge,municipio,procedimento,valor`.
- `scripts/sisab_saude_condicao_avaliada.py` / `sisab-saude-condicao-avaliada`: Coluna `Probl/ Condição Avaliada`; select all `Problema/Condição Avaliada`; output `competencia,uf,ibge,municipio,condicao_avaliada,valor`.

Preserve:

- SISAB is slow/flaky: keep long timeouts, retries, backoff, delays, adaptive chunks.
- Missing municipality rows can mean zero events: retry that case once, then continue.
- Revalidate cached raw chunks before reuse; malformed cached chunks must be redownloaded.
- Never write final CSV until the full requested run succeeds; partial final output is useless.
- Competência ranges write separate CSVs; `--output` is single-month only.
- Keep raw chunk cache/resume, cache locks, municipality caching, sorted final rows, validation.
- Repeated single-municipality missing rows are accepted after the one confirmation retry; other repeated failures abort.
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
