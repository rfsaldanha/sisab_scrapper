# sisab_scrapper

Scrapers for the SISAB Saúde: Atendimento/Visita production report:

https://sisab.saude.gov.br/paginas/acessoRestrito/relatorio/municipio/saude/RelSauProducao.xhtml

All scrapers use the same base configuration:

- Unidade geográfica: `Municípios`
- Estado: all UFs
- Município: all municipalities
- Competência: one month or an inclusive month interval
- Linha: `Municipio`
- Faixa etária: DataSUS `Faixa etária 2` groups
- Sexo: `Masculino` and `Feminino`
- Output: tidy CSV, one final CSV ZIP per competência

For each scraper and competência, the final CSV ZIP combines 36 SISAB downloads:
18 age groups x 2 sex values. This keeps the final artifact per competência
while preserving raw-cache resume for each age/sex stratum.

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

Pass an inclusive competência interval to write one separate CSV ZIP per month:

```bash
python3 scripts/sisab_saude_producao.py --competencia 202601 202604
```

Default output paths include the scraper name and competência:

```text
data/producao/monthly/sisab_saude_producao_202604.csv.zip
data/procedimento/monthly/sisab_saude_procedimento_202604.csv.zip
data/condicao_avaliada/monthly/sisab_saude_condicao_avaliada_202604.csv.zip
```

Use `--output-dir` to change the directory for default outputs.

## Yearly merge

`merge_files.R` joins monthly scraper outputs into yearly CSV ZIP and parquet files.
It expects the stratified monthly schema shown below, including `faixa_etaria`
and `sexo`.

```bash
Rscript scripts/merge_files.R 2026
```

By default, it reads:

```text
data/producao/monthly
data/procedimento/monthly
data/condicao_avaliada/monthly
```

and writes:

```text
data/producao/yearly/sisab_saude_producao_2026.csv.zip
data/producao/yearly/sisab_saude_producao_2026.parquet
data/procedimento/yearly/sisab_saude_procedimento_2026.csv.zip
data/procedimento/yearly/sisab_saude_procedimento_2026.parquet
data/condicao_avaliada/yearly/sisab_saude_condicao_avaliada_2026.csv.zip
data/condicao_avaliada/yearly/sisab_saude_condicao_avaliada_2026.parquet
```

For each year and scraper, the merge expands the observed municipalities and
categories across all input competências, all 18 age groups, and both sex
values. Missing month/municipality/age/sex/category combinations are written
with `valor = 0`.

Useful options:

```bash
Rscript scripts/merge_files.R --year 2026 --data-dir data
Rscript scripts/merge_files.R 2026 --allow-month-gaps
```

Without `--allow-month-gaps`, the script stops if there are missing monthly
files between the first and last competência found for the year. It also
validates expected age groups, sex values, required columns, and empty category
values before writing yearly outputs.

## Schemas

`sisab-saude-producao`:

```text
competencia,uf,ibge,municipio,faixa_etaria,sexo,tipo_producao,valor
```

`sisab-saude-procedimento`:

```text
competencia,uf,ibge,municipio,faixa_etaria,sexo,procedimento,valor
```

`sisab-saude-condicao-avaliada`:

```text
competencia,uf,ibge,municipio,faixa_etaria,sexo,condicao_avaliada,valor
```

## Reliability

Each final CSV ZIP is written atomically after its competência run succeeds.

Raw all-Brazil SISAB CSV ZIPs are cached by scraper under:

```text
data/raw/sisab_saude_producao
data/raw/sisab_saude_procedimento
data/raw/sisab_saude_condicao_avaliada
```

Within each scraper cache, raw CSV ZIPs are separated by competência, age group, and
sex, for example:

```text
data/raw/sisab_saude_producao/202604/de_20_a_24_anos/feminino/brasil.csv.zip
```

Use `--no-resume` to ignore cached raw CSV ZIPs and legacy CSVs, or `--no-raw-cache` to avoid saving
them. Raw cache writes use lock files so concurrent runs do not write the same
CSV ZIP at once.

New runs write `.csv.zip` archives containing one CSV member with the original
`.csv` filename. Readers still accept legacy plain `.csv` files, preferring the
ZIP file when both exist.

Convert existing CSVs after a run with the command below. Existing `.csv.zip` files are rebuilt and overwritten from their matching plain `.csv` files:

```bash
sisab-zip-csv-files data
sisab-zip-csv-files --dry-run data
```

SISAB is slow and intermittently unreliable. Defaults are conservative:

- `--delay 2`
- `--timeout 900`
- `--retries 10`
- exponential retry backoff with jitter

```bash
python3 scripts/sisab_saude_producao.py --competencia 202604 --delay 5 --timeout 1200 --retry-backoff 10
```

Each scraper validates that the requested competência exists on SISAB and writes
sorted final rows. Cached raw CSV ZIPs and legacy CSVs are revalidated before reuse; invalid
caches are redownloaded.

Use JSON-lines progress logs when running from automation:

```bash
python3 scripts/sisab_saude_producao.py --competencia 202604 --json-log
```

## Tests

```bash
python3 -m unittest discover -s tests
Rscript -e "testthat::test_file('tests/test_merge_files.R')"
```
