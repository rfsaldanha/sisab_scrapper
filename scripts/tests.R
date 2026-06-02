# Packages
library(dplyr)
library(lubridate)
library(readr)
library(arrow)
library(fs)
library(glue)

procedimento <- open_dataset(
  sources = dir_ls(path("data/procedimento/yearly/"), regexp = ".parquet")
)

procedimento |>
  select(procedimento) |>
  distinct(procedimento) |>
  collect()

procedimento |>
  filter(procedimento == "Adm. Med. inalação/nebulização") |>
  filter(ibge == "330455") |>
  arrange(competencia) |>
  collect() |>
  View()

condicao_avaliada <- open_dataset(
  sources = dir_ls(path("data/condicao_avaliada/yearly/"), regexp = ".parquet")
)

condicao_avaliada |>
  select(condicao_avaliada) |>
  distinct(condicao_avaliada) |>
  collect()

condicao_avaliada |>
  filter(condicao_avaliada == "Diabetes") |>
  filter(ibge == "330455") |>
  arrange(competencia) |>
  collect() |>
  View()

producao <- open_dataset(
  sources = dir_ls(path("data/producao/yearly/"), regexp = ".parquet")
)

producao |>
  select(tipo_producao) |>
  distinct(tipo_producao) |>
  collect()

producao |>
  filter(tipo_producao == "Atendimento Individual") |>
  filter(ibge == "330455") |>
  arrange(competencia) |>
  collect() |>
  View()
