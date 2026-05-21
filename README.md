# sisab_scrapper

Scrapers for the SISAB Saúde: Atendimento/Visita production report:

https://sisab.saude.gov.br/paginas/acessoRestrito/relatorio/federal/saude/RelSauProducao.xhtml

All scrapers use the same base configuration:

- Unidade geográfica: `Municípios`
- Estado: all UFs by default, or selected UFs with `--state`
- Município: all municipalities loaded from each selected UF
- Competência: one month or an inclusive month interval
- Linha: `Municipio`
- Output: tidy CSV, one final CSV per competência

Available scrapers:

| Script | Installed command | Coluna do relatório | Extra filter | Output value column |
| --- | --- | --- | --- | --- |
| `scripts/sisab_saude_producao.py` | `sisab-saude-producao` | `Tipo de Produção` | none | `tipo_producao` |
| `scripts/sisab_saude_procedimento.py` | `sisab-saude-procedimento` | `Procedimento` | all `Procedimento` options selected | `procedimento` |
| `scripts/sisab_saude_condicao_avaliada.py` | `sisab-saude-condicao-avaliada` | `Probl/ Condição Avaliada` | all `Problema/Condição Avaliada` options selected | `condicao_avaliada` |

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
python3 scripts/sisab_saude_procedimento.py --competencia 202604
python3 scripts/sisab_saude_condicao_avaliada.py --competencia 202604
```

The installed commands are equivalent:

```bash
sisab-saude-producao --competencia 202604
sisab-saude-procedimento --competencia 202604
sisab-saude-condicao-avaliada --competencia 202604
```

Pass an inclusive competência interval to write one separate CSV per month:

```bash
python3 scripts/sisab_saude_producao.py --competencia 202601 202604
```

Default output paths include the scraper name, competência, and UF label:

```text
data/sisab_saude_producao_202604_all_ufs.csv
data/sisab_saude_procedimento_202604_AC.csv
data/sisab_saude_condicao_avaliada_202604_AC_SP.csv
```

Use `--output-dir` to change the directory for default outputs. Use `--output`
only for single-competência runs.

Limit UFs with repeated `--state`:

```bash
python3 scripts/sisab_saude_producao.py --competencia 202604 --state AC --state SP
```

## Schemas

`sisab-saude-producao`:

```text
competencia,uf,ibge,municipio,tipo_producao,valor
```

`sisab-saude-procedimento`:

```text
competencia,uf,ibge,municipio,procedimento,valor
```

`sisab-saude-condicao-avaliada`:

```text
competencia,uf,ibge,municipio,condicao_avaliada,valor
```

## Reliability

The final CSV is written atomically only after the whole requested run succeeds.
Partial final outputs are not produced.

Raw SISAB CSV chunks are cached by scraper under:

```text
data/raw/sisab_saude_producao
data/raw/sisab_saude_procedimento
data/raw/sisab_saude_condicao_avaliada
```

Use `--no-resume` to ignore cached chunks, or `--no-raw-cache` to avoid saving
them. Raw cache writes use lock files so concurrent runs do not write the same
chunk at once.

SISAB is slow and intermittently unreliable. Defaults are conservative:

- `--delay 2`
- `--timeout 900`
- `--retries 10`
- exponential retry backoff with jitter
- `--municipality-chunk-size 10`
- adaptive chunk splitting after repeated chunk failures
- missing municipality rows are retried once, then treated as zero-event municipalities

```bash
python3 scripts/sisab_saude_producao.py --competencia 202604 --delay 5 --timeout 1200 --retry-backoff 10
```

Each scraper validates that the requested competência exists on SISAB and writes
sorted final rows. If SISAB returns no rows for a requested municipality, the
chunk is retried once to confirm the absence, then the run continues. Cached raw
chunks are revalidated before reuse; invalid cached chunks are redownloaded.

Use JSON-lines progress logs when running from automation:

```bash
python3 scripts/sisab_saude_producao.py --competencia 202604 --json-log
```

## Tests

```bash
python3 -m unittest discover -s tests
```
