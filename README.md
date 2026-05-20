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

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python3 scripts/sisab_saude_producao.py --competencia 202604
```

The default output path is:

```text
data/sisab_saude_producao_202604.csv
```

The CSV columns are:

```text
competencia,uf,ibge,municipio,tipo_producao,tipo_producao_slug,valor
```

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
before aborting:

```bash
python3 scripts/sisab_saude_producao.py --competencia 202604 --timeout 1200 --retries 10
```

Large UFs are split into municipality chunks before download to avoid SISAB
server errors/timeouts on very large form submissions. The default chunk size is
10:

```bash
python3 scripts/sisab_saude_producao.py --competencia 202604 --municipality-chunk-size 50
```
