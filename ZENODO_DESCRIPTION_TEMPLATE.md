# Zenodo Description Template

## Title suggestion

SISAB municipal primary care production and CID/CIAP attendance data, Brazil, {YEAR}

## Description

This deposit contains annual, municipality-level datasets derived from the Brazilian Primary Health Care Information System (SISAB). The files combine two complementary data sources:

1. Public SISAB Saúde report downloads from the Atendimento/Visita production report.
2. CID-10 and CIAP-2 attendance data obtained from SISAB through requests under the Brazilian Access to Information Law (Lei de Acesso à Informação, LAI).

The datasets are organized as tidy annual files in CSV (Zipped) and Parquet format. They are intended to support reproducible analysis of primary care production, procedures, evaluated problems/conditions, and CID/CIAP-coded attendances across Brazilian municipalities.

The public SISAB report datasets are stratified by competence month, state, municipality, DataSUS age group, SISAB sex category, and the selected report category. For each competence month and report type, the extraction combines 36 stratified SISAB downloads: 18 age groups by 2 sex values. Monthly files are merged into yearly files, completing missing combinations of observed competence, municipality, age group, sex, and category with `valor = 0`.

The LAI dataset contains yearly CID-10 and CIAP-2 attendance counts by competence month, municipality, code type, and code. When multiple valid LAI files cover the same competence, the processing pipeline selects the file with the largest number of data rows, using file size and request folder order as tie-breakers. Provenance columns identify the selected LAI request and source file.

## Variables

### SISAB Saúde Produção

Columns:

- `competencia`: competence month in `YYYYMM` format.
- `uf`: Brazilian state abbreviation.
- `ibge`: municipality IBGE code.
- `municipio`: municipality name.
- `faixa_etaria`: DataSUS `Faixa etária 2` age group.
- `sexo`: SISAB sex category, `Masculino` or `Feminino`.
- `tipo_producao`: production type from the SISAB report.
- `valor`: count reported by SISAB.

### SISAB Saúde Procedimento

Columns:

- `competencia`: competence month in `YYYYMM` format.
- `uf`: Brazilian state abbreviation.
- `ibge`: municipality IBGE code.
- `municipio`: municipality name.
- `faixa_etaria`: DataSUS `Faixa etária 2` age group.
- `sexo`: SISAB sex category, `Masculino` or `Feminino`.
- `procedimento`: procedure from the SISAB report.
- `valor`: count reported by SISAB.

### SISAB Saúde Condição Avaliada

Columns:

- `competencia`: competence month in `YYYYMM` format.
- `uf`: Brazilian state abbreviation.
- `ibge`: municipality IBGE code.
- `municipio`: municipality name.
- `faixa_etaria`: DataSUS `Faixa etária 2` age group.
- `sexo`: SISAB sex category, `Masculino` or `Feminino`.
- `condicao_avaliada`: evaluated problem or condition from the SISAB report.
- `valor`: count reported by SISAB.

### SISAB LAI CID/CIAP

Columns:

- `ano_competencia`: competence year.
- `competencia`: competence month in `YYYYMM` format.
- `competencia_date`: first day of the competence month.
- `co_municipio_ibge`: municipality IBGE code.
- `tp_codigo`: code type, `CID` or `CIAP`.
- `codigo`: CID-10 or CIAP-2 code.
- `qt_atendimentos`: number of attendances.
- `source_request`: selected LAI request folder.
- `source_file`: selected source CSV file.

## Methods

The public SISAB report files were generated with the `sisab_scrapper` processing pipeline. For each month, report type, age group, and sex value, the pipeline downloads the all-Brazil municipality report from SISAB, validates the returned CSV, preserves raw cache files for resumable runs, and writes a sorted monthly tidy dataset. The yearly merge validates required columns, expected age groups, expected sex values, category values, and month gaps unless explicitly allowed.

The CID/CIAP files were generated with the `sisab_lai` processing pipeline. The pipeline imports CSV files received through LAI requests, detects the real CSV header after any SQL*Plus preamble, validates candidate files, resolves overlapping requests by competence, standardizes old and new schemas into one tidy table, and exports annual CSV and Parquet files together with audit reports.

## Sources

- SISAB public reports, Ministry of Health, Brazil: https://sisab.saude.gov.br/
- SISAB LAI files obtained through Brazilian Access to Information Law requests.
- Processing code for public SISAB report data: https://github.com/rfsaldanha/sisab_scrapper
- Processing code for LAI CID/CIAP data: https://github.com/rfsaldanha/sisab_lai

## Notes

- Counts are aggregated administrative records and should be interpreted in light of SISAB reporting practices, data quality, and changes in municipal reporting coverage.
- Municipality boundaries, names, and coding practices may vary over time.
- Public SISAB report datasets are completed with zero values only for combinations defined by observed municipalities, observed competencies, all expected age groups, both expected sex values, and observed report categories within the yearly merge.
- LAI CID/CIAP data preserve selected source-file provenance through `source_request` and `source_file`.
- This deposit corresponds to the year {YEAR}. Deposits for other years are published separately.
