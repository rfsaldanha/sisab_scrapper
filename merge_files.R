# Packages
library(dplyr)
library(lubridate)
library(readr)
library(arrow)
library(fs)
library(glue)

# Year
year <- 2026

# Folders
producao_folder <- path("data/producao/")
procedimento_folder <- path("data/procedimento/")
condicao_avaliada_folder <- path("data/condicao_avaliada/")

# Files list
producao_files <- dir_ls(
  path = path(producao_folder, "monthly"),
  regexp = year
)
procedimento_files <- dir_ls(
  path = path(procedimento_folder, "monthly"),
  regexp = year
)
condicao_avaliada_files <- dir_ls(
  path = path(condicao_avaliada_folder, "monthly"),
  regexp = year
)

# Read files
producao_data <- read_csv(
  file = producao_files,
  col_types = cols(
    competencia = col_character(),
    uf = col_character(),
    ibge = col_character(),
    municipio = col_character(),
    tipo_producao = col_character(),
    valor = col_integer()
  )
)
procedimento_data <- read_csv(
  file = procedimento_files,
  col_types = cols(
    competencia = col_character(),
    uf = col_character(),
    ibge = col_character(),
    municipio = col_character(),
    procedimento = col_character(),
    valor = col_integer()
  )
)
condicao_avaliada_data <- read_csv(
  file = condicao_avaliada_files,
  col_types = cols(
    competencia = col_character(),
    uf = col_character(),
    ibge = col_character(),
    municipio = col_character(),
    condicao_avaliada = col_character(),
    valor = col_integer()
  )
)

# Export files
write_csv2(
  x = producao_data,
  file = path(
    producao_folder,
    "yearly",
    glue("sisab_saude_producao_{year}.csv")
  )
)
write_parquet(
  x = producao_data,
  sink = path(
    producao_folder,
    "yearly",
    glue("sisab_saude_producao_{year}.parquet")
  )
)
write_csv2(
  x = procedimento_data,
  file = path(
    procedimento_folder,
    "yearly",
    glue("sisab_saude_procedimento_{year}.csv")
  )
)
write_parquet(
  x = procedimento_data,
  sink = path(
    procedimento_folder,
    "yearly",
    glue("sisab_saude_procedimento_{year}.parquet")
  )
)
write_csv2(
  x = condicao_avaliada_data,
  file = path(
    condicao_avaliada_folder,
    "yearly",
    glue("sisab_saude_condicao_avaliada_{year}.csv")
  )
)
write_parquet(
  x = condicao_avaliada_data,
  sink = path(
    condicao_avaliada_folder,
    "yearly",
    glue("sisab_saude_condicao_avaliada_{year}.parquet")
  )
)
