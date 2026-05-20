# sisab_scrapper

Scraper for the SISAB Saúde: Atendimento/Visita production report:

https://sisab.saude.gov.br/paginas/acessoRestrito/relatorio/federal/saude/RelSauProducao.xhtml

Current configuration:

- Unidade geográfica: `Municípios`
- Estado: all UFs by default
- Município: all municipalities in each selected UF
- Competência: exactly one per run
- Linha: `Municipio`
- Coluna: `Tipo de Produção`
- Filters: none
- Output: tidy CSV

There is also a sibling scraper for the same report with:

- Coluna: `Procedimento`
- Procedimento filter: all options selected
- Output: tidy CSV with one row per municipality/procedimento

And another sibling scraper with:

- Coluna: `Probl/ Condição Avaliada`
- Problema/Condição Avaliada filter: all options selected
- Output: tidy CSV with one row per municipality/condição avaliada

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

You can also install the command entry point:

```bash
pip install -e .
sisab-saude-producao --help
sisab-saude-procedimento --help
sisab-saude-condicao-avaliada --help
```

## Run

```bash
python3 scripts/sisab_saude_producao.py --competencia 202604
```

For the Procedimento report:

```bash
python3 scripts/sisab_saude_procedimento.py --competencia 202604
```

For the Problema/Condição Avaliada report:

```bash
python3 scripts/sisab_saude_condicao_avaliada.py --competencia 202604
```

You can also pass an inclusive competência interval. This writes one separate
CSV per month:

```bash
python3 scripts/sisab_saude_producao.py --competencia 202601 202604
```

The default output path is:

```text
data/sisab_saude_producao_202604_all_ufs.csv
```

For state-limited runs, the default file includes the selected UF acronym(s),
for example `data/sisab_saude_producao_202604_AC.csv` or
`data/sisab_saude_producao_202604_AC_SP.csv`. Use `--output-dir` to change the
directory for default outputs. `--output` is only accepted for single-competência
runs.

The CSV columns are:

```text
competencia,uf,ibge,municipio,tipo_producao,valor
```

The Procedimento CSV columns are:

```text
competencia,uf,ibge,municipio,procedimento,valor
```

The Problema/Condição Avaliada CSV columns are:

```text
competencia,uf,ibge,municipio,condicao_avaliada,valor
```

The final CSV is written atomically only after the whole requested run succeeds.
Raw SISAB CSV chunks are cached under `data/raw/sisab_saude_producao` so failed
runs can resume without redownloading completed chunks. Use `--no-resume` to
ignore cached chunks, or `--no-raw-cache` to avoid saving them. Raw cache writes
use lock files so concurrent runs do not write the same chunk at once.

To test with only one UF:

```bash
python3 scripts/sisab_saude_producao.py --competencia 202604 --state SP --output data/sp_202604.csv
```

The scraper waits before every HTTP request. The default delay is 2 seconds:

```bash
python3 scripts/sisab_saude_producao.py --competencia 202604 --delay 5
```

SISAB can be slow and intermittently unreliable. By default the scraper uses a
900 second HTTP timeout and retries failed HTTP/download requests 10 times
before aborting. Retries use exponential backoff with jitter:

```bash
python3 scripts/sisab_saude_producao.py --competencia 202604 --timeout 1200 --retries 10 --retry-backoff 10
```

Large UFs are split into municipality chunks before download to avoid SISAB
server errors/timeouts on very large form submissions. The default chunk size is
10:

```bash
python3 scripts/sisab_saude_producao.py --competencia 202604 --municipality-chunk-size 50
```

If a chunk still fails after all retries, the scraper splits it into smaller
chunks by default. A single-municipality failure aborts the run.

The script validates that the requested competência exists on the SISAB page and
that all requested municipalities and expected production categories are present
before creating the final tidy CSV. Final rows are sorted by competência, UF,
municipality IBGE code, and production type.

For machine-readable progress logs:

```bash
python3 scripts/sisab_saude_producao.py --competencia 202604 --json-log
```

## Tests

```bash
python3 -m unittest discover -s tests
```
