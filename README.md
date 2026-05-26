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
- Output: tidy CSV, one final CSV per competência

For each scraper and competência, the final CSV combines 36 SISAB downloads:
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

Pass an inclusive competência interval to write one separate CSV per month:

```bash
python3 scripts/sisab_saude_producao.py --competencia 202601 202604
```

Default output paths include the scraper name and competência:

```text
data/sisab_saude_producao_202604.csv
data/sisab_saude_procedimento_202604.csv
data/sisab_saude_condicao_avaliada_202604.csv
```

Use `--output-dir` to change the directory for default outputs.

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

Each final CSV is written atomically after its competência run succeeds.

Raw all-Brazil SISAB CSVs are cached by scraper under:

```text
data/raw/sisab_saude_producao
data/raw/sisab_saude_procedimento
data/raw/sisab_saude_condicao_avaliada
```

Within each scraper cache, raw CSVs are separated by competência, age group, and
sex, for example:

```text
data/raw/sisab_saude_producao/202604/de_20_a_24_anos/feminino/brasil.csv
```

Use `--no-resume` to ignore cached raw CSVs, or `--no-raw-cache` to avoid saving
them. Raw cache writes use lock files so concurrent runs do not write the same
CSV at once.

SISAB is slow and intermittently unreliable. Defaults are conservative:

- `--delay 2`
- `--timeout 900`
- `--retries 10`
- exponential retry backoff with jitter

```bash
python3 scripts/sisab_saude_producao.py --competencia 202604 --delay 5 --timeout 1200 --retry-backoff 10
```

Each scraper validates that the requested competência exists on SISAB and writes
sorted final rows. Cached raw CSVs are revalidated before reuse; invalid cached
CSVs are redownloaded.

Use JSON-lines progress logs when running from automation:

```bash
python3 scripts/sisab_saude_producao.py --competencia 202604 --json-log
```

## Tests

```bash
python3 -m unittest discover -s tests
```
