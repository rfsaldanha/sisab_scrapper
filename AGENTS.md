# AGENTS.md

SISAB Saúde Produção scrapers. Shared base: municipality-level report URL; all UFs and all municipalities per request; Linha `Municipio`; stratify every scraper/competência by DataSUS `Faixa etária 2` age groups and SISAB sex (`Masculino`, `Feminino`); tidy CSV; one final CSV per competência.

Scripts/commands:

- `scripts/sisab_saude_producao.py` / `sisab-saude-producao`: Coluna `Tipo de Produção`; output `competencia,uf,ibge,municipio,faixa_etaria,sexo,tipo_producao,valor`.
- `scripts/sisab_saude_procedimento.py` / `sisab-saude-procedimento`: Coluna `Procedimento`; select all `Procedimento`; output `competencia,uf,ibge,municipio,faixa_etaria,sexo,procedimento,valor`.
- `scripts/sisab_saude_condicao_avaliada.py` / `sisab-saude-condicao-avaliada`: Coluna `Probl/ Condição Avaliada`; select all `Problema/Condição Avaliada`; output `competencia,uf,ibge,municipio,faixa_etaria,sexo,condicao_avaliada,valor`.

Preserve:

- SISAB is slow/flaky: keep long timeouts, retries, backoff, and delays.
- Each scraper/competência performs 36 stratified downloads: 18 age groups x 2 sex values.
- Revalidate cached raw Brazil CSVs before reuse; malformed cached CSVs must be redownloaded.
- Final CSVs are per competência and must be written atomically.
- Keep raw CSV cache/resume by competência/faixa_etaria/sexo, cache locks, sorted final rows, and validation.
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
