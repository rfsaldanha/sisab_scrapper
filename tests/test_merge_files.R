library(testthat)
library(dplyr)
library(tibble)

merge_candidates <- Filter(file.exists, c("../scripts/merge_files.R", "scripts/merge_files.R", "merge_files.R", "../merge_files.R"))
source(merge_candidates[[1]])

test_that("complete_yearly_data fills missing month age sex category combinations", {
  monthly <- tibble(
    competencia = c("202601", "202602"),
    uf = "AC",
    ibge = "120001",
    municipio = "ACRELANDIA",
    faixa_etaria = c("Menor de 1 ano", "De 1 a 4 anos"),
    sexo = c("Masculino", "Feminino"),
    procedimento = "Teste",
    valor = c(5, 7)
  )

  completed <- complete_yearly_data(
    monthly,
    competencias = c("202601", "202602"),
    category_col = "procedimento"
  )

  expect_equal(nrow(completed), 72)
  expect_equal(sum(completed$valor), 12)
  expect_type(completed$valor, "integer")

  missing_combo <- completed |>
    filter(
      competencia == "202601",
      faixa_etaria == "De 1 a 4 anos",
      sexo == "Feminino",
      procedimento == "Teste"
    )

  expect_equal(nrow(missing_combo), 1)
  expect_equal(missing_combo$valor, 0L)
})

test_that("streaming yearly writer matches completed data", {
  monthly <- tibble(
    competencia = c("202601", "202602"),
    uf = "AC",
    ibge = "120001",
    municipio = "ACRELANDIA",
    faixa_etaria = c("Menor de 1 ano", "De 1 a 4 anos"),
    sexo = c("Masculino", "Feminino"),
    procedimento = c("A", "B"),
    valor = c(5, 7)
  )
  competencias <- c("202601", "202602")
  expected <- complete_yearly_data(monthly, competencias, "procedimento")
  output_dir <- tempdir()
  csv_path <- file.path(output_dir, "yearly.csv")
  parquet_path <- file.path(output_dir, "yearly.parquet")

  write_completed_yearly_atomic(
    summarise_yearly_data(monthly, "procedimento"),
    competencias,
    "procedimento",
    csv_path,
    parquet_path
  )

  from_csv <- readr::read_csv2(
    csv_path,
    col_types = readr::cols(
      .default = readr::col_character(),
      valor = readr::col_integer()
    ),
    show_col_types = FALSE
  )
  from_parquet <- arrow::read_parquet(parquet_path)

  expect_identical(as_tibble(from_csv), expected)
  expect_identical(as_tibble(from_parquet), expected)
})

test_that("validate_dimensions rejects unexpected age groups and sexes", {
  monthly <- tibble(
    competencia = "202601",
    uf = "AC",
    ibge = "120001",
    municipio = "ACRELANDIA",
    faixa_etaria = "30 anos",
    sexo = "Ignorado",
    procedimento = "Teste",
    valor = 1
  )

  expect_error(
    validate_dimensions(monthly, "procedimento"),
    "Unexpected faixa_etaria values"
  )
})

test_that("validate_months detects gaps between first and last monthly files", {
  files <- c(
    "data/procedimento/monthly/sisab_saude_procedimento_202601.csv",
    "data/procedimento/monthly/sisab_saude_procedimento_202603.csv"
  )

  expect_error(validate_months(files), "Missing monthly files")
  expect_equal(validate_months(files, allow_month_gaps = TRUE), c("202601", "202603"))
})

test_that("monthly file patterns are specific to one scraper and year", {
  pattern <- monthly_file_pattern("sisab_saude_producao", "2026")

  expect_true(grepl(pattern, "sisab_saude_producao_202601.csv"))
  expect_false(grepl(pattern, "sisab_saude_producao_202601.csv.bak"))
  expect_false(grepl(pattern, "sisab_saude_procedimento_202601.csv"))
  expect_false(grepl(pattern, "sisab_saude_producao_202501.csv"))
})
