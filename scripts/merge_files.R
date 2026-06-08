# Packages
library(dplyr)
library(readr)
library(arrow)
library(fs)
library(glue)
library(tibble)
library(tidyr)

# Dimensions
age_groups <- c(
  "Menor de 1 ano",
  "De 1 a 4 anos",
  "De 5 a 9 anos",
  "De 10 a 14 anos",
  "De 15 a 19 anos",
  "De 20 a 24 anos",
  "De 25 a 29 anos",
  "De 30 a 34 anos",
  "De 35 a 39 anos",
  "De 40 a 44 anos",
  "De 45 a 49 anos",
  "De 50 a 54 anos",
  "De 55 a 59 anos",
  "De 60 a 64 anos",
  "De 65 a 69 anos",
  "De 70 a 74 anos",
  "De 75 a 79 anos",
  "80 anos ou mais"
)
sexes <- c("Masculino", "Feminino")

# Dataset config
datasets <- tribble(
  ~name               , ~folder             , ~category_col       , ~file_prefix                    ,
  "producao"          , "producao"          , "tipo_producao"     , "sisab_saude_producao"          ,
  "procedimento"      , "procedimento"      , "procedimento"      , "sisab_saude_procedimento"      ,
  "condicao_avaliada" , "condicao_avaliada" , "condicao_avaliada" , "sisab_saude_condicao_avaliada"
)

parse_args <- function(args = commandArgs(trailingOnly = TRUE)) {
  if (length(args) == 1 && args[[1]] %in% c("-h", "--help")) {
    cat(
      "Usage: Rscript merge_files.R [YEAR] [--data-dir PATH] [--allow-month-gaps]\n"
    )
    quit(status = 0)
  }

  year <- NULL
  data_dir <- "data"
  allow_month_gaps <- FALSE
  index <- 1

  while (index <= length(args)) {
    arg <- args[[index]]
    if (arg == "--year") {
      index <- index + 1
      year <- args[[index]]
    } else if (arg == "--data-dir") {
      index <- index + 1
      data_dir <- args[[index]]
    } else if (arg == "--allow-month-gaps") {
      allow_month_gaps <- TRUE
    } else if (is.null(year) && grepl("^[0-9]{4}$", arg)) {
      year <- arg
    } else {
      stop(glue("Unknown argument: {arg}"), call. = FALSE)
    }
    index <- index + 1
  }

  if (is.null(year)) {
    year <- format(Sys.Date(), "%Y")
  }
  if (!grepl("^[0-9]{4}$", year)) {
    stop(glue("Invalid year: {year}"), call. = FALSE)
  }

  list(
    year = year,
    data_dir = data_dir,
    allow_month_gaps = allow_month_gaps
  )
}

monthly_file_pattern <- function(file_prefix, year) {
  glue("^{file_prefix}_{year}[0-9]{{2}}\\.csv(\\.zip)?$")
}

prefer_zipped_monthly_files <- function(files) {
  if (length(files) == 0) {
    return(files)
  }

  keys <- extract_competencias(files)
  selected <- vapply(keys, function(competencia) {
    candidates <- files[grepl(competencia, path_file(files), fixed = TRUE)]
    zipped <- candidates[grepl("\\.csv\\.zip$", path_file(candidates))]
    if (length(zipped) > 0) {
      return(sort(zipped)[[1]])
    }
    sort(candidates)[[1]]
  }, character(1))

  sort(unname(selected))
}

list_monthly_files <- function(data_dir, folder, file_prefix, year) {
  monthly_dir <- path(data_dir, folder, "monthly")
  if (!dir_exists(monthly_dir)) {
    stop(glue("Monthly directory does not exist: {monthly_dir}"), call. = FALSE)
  }

  files <- dir_ls(path = monthly_dir, type = "file")
  files[grepl(monthly_file_pattern(file_prefix, year), path_file(files))] |>
    prefer_zipped_monthly_files()
}

extract_competencias <- function(files) {
  competencias <- regmatches(
    path_file(files),
    regexpr("[0-9]{6}", path_file(files))
  )
  sort(unique(competencias))
}

validate_months <- function(files, allow_month_gaps = FALSE) {
  competencias <- extract_competencias(files)
  if (length(competencias) == 0) {
    return(competencias)
  }
  if (allow_month_gaps || length(competencias) == 1) {
    return(competencias)
  }

  first_month <- as.Date(paste0(competencias[[1]], "01"), format = "%Y%m%d")
  last_month <- as.Date(
    paste0(competencias[[length(competencias)]], "01"),
    format = "%Y%m%d"
  )
  expected <- format(seq(first_month, last_month, by = "month"), "%Y%m")
  missing <- setdiff(expected, competencias)

  if (length(missing) > 0) {
    stop(
      glue(
        "Missing monthly files between {competencias[[1]]} and {competencias[[length(competencias)]]}: ",
        glue_collapse(missing, sep = ", "),
        ". Use --allow-month-gaps to merge anyway."
      ),
      call. = FALSE
    )
  }

  competencias
}

validate_dimensions <- function(data, category_col) {
  invalid_age_groups <- setdiff(unique(data$faixa_etaria), age_groups)
  invalid_sexes <- setdiff(unique(data$sexo), sexes)
  missing_categories <- data |>
    filter(is.na(.data[[category_col]]) | .data[[category_col]] == "")

  if (length(invalid_age_groups) > 0) {
    stop(
      glue(
        "Unexpected faixa_etaria values: ",
        glue_collapse(sort(invalid_age_groups), sep = ", ")
      ),
      call. = FALSE
    )
  }
  if (length(invalid_sexes) > 0) {
    stop(
      glue(
        "Unexpected sexo values: ",
        glue_collapse(sort(invalid_sexes), sep = ", ")
      ),
      call. = FALSE
    )
  }
  if (nrow(missing_categories) > 0) {
    stop(glue("Found empty {category_col} values."), call. = FALSE)
  }

  invisible(data)
}

zip_csv_member <- function(zip_path, expected = NULL) {
  listing <- unzip(zip_path, list = TRUE)
  members <- listing$Name[!grepl("/$", listing$Name)]
  if (is.null(expected)) {
    expected <- sub("\\.zip$", "", path_file(zip_path))
  }
  if (!identical(members, expected)) {
    stop(
      glue("Expected ZIP {zip_path} to contain only {expected}."),
      call. = FALSE
    )
  }
  expected
}

read_one_monthly_file <- function(file, col_types) {
  if (grepl("\\.csv\\.zip$", path_file(file))) {
    member <- zip_csv_member(file)
    connection <- unz(file, member, open = "rb")
    on.exit(close(connection), add = TRUE)
    return(read_csv(
      file = connection,
      col_types = col_types,
      show_col_types = FALSE
    ))
  }

  read_csv(
    file = file,
    col_types = col_types,
    show_col_types = FALSE
  )
}

read_monthly_files <- function(files, category_col) {
  required_cols <- c(
    "competencia",
    "uf",
    "ibge",
    "municipio",
    "faixa_etaria",
    "sexo",
    category_col,
    "valor"
  )

  if (length(files) == 0) {
    stop("No monthly files found.", call. = FALSE)
  }

  monthly_col_types <- cols(
    .default = col_character(),
    competencia = col_character(),
    uf = col_character(),
    ibge = col_character(),
    municipio = col_character(),
    faixa_etaria = col_character(),
    sexo = col_character(),
    valor = col_double()
  )
  data <- lapply(files, read_one_monthly_file, col_types = monthly_col_types) |>
    bind_rows()

  missing_cols <- setdiff(required_cols, names(data))
  if (length(missing_cols) > 0) {
    stop(
      glue(
        "Monthly files for {category_col} are missing required columns: ",
        glue_collapse(missing_cols, sep = ", ")
      ),
      call. = FALSE
    )
  }

  data |>
    select(all_of(required_cols)) |>
    mutate(
      competencia = as.character(competencia),
      ibge = as.character(ibge),
      valor = coalesce(valor, 0)
    ) |>
    validate_dimensions(category_col)
}

complete_yearly_data <- function(data, competencias, category_col) {
  category <- sym(category_col)

  summarise_yearly_data(data, category_col) |>
    complete(
      competencia = competencias,
      nesting(uf, ibge, municipio),
      faixa_etaria = age_groups,
      sexo = sexes,
      nesting(!!category),
      fill = list(valor = 0)
    ) |>
    mutate(valor = as.integer(valor)) |>
    arrange(
      competencia,
      uf,
      ibge,
      faixa_etaria,
      sexo,
      !!category
    ) |>
    select(
      competencia,
      uf,
      ibge,
      municipio,
      faixa_etaria,
      sexo,
      all_of(category_col),
      valor
    )
}

summarise_yearly_data <- function(data, category_col) {
  data |>
    group_by(across(all_of(c(
      "competencia",
      "uf",
      "ibge",
      "municipio",
      "faixa_etaria",
      "sexo",
      category_col
    )))) |>
    summarise(valor = sum(valor, na.rm = TRUE), .groups = "drop") |>
    mutate(valor = as.integer(valor)) |>
    select(
      competencia,
      uf,
      ibge,
      municipio,
      faixa_etaria,
      sexo,
      all_of(category_col),
      valor
    )
}

read_and_summarise_monthly_files <- function(files, category_col) {
  summaries <- vector("list", length(files))
  for (file_index in seq_along(files)) {
    data <- read_monthly_files(files[[file_index]], category_col)
    summaries[[file_index]] <- summarise_yearly_data(data, category_col)
    rm(data)
    gc()
  }

  bind_rows(summaries) |>
    summarise_yearly_data(category_col)
}

yearly_schema <- function(category_col) {
  fields <- list(
    competencia = string(),
    uf = string(),
    ibge = string(),
    municipio = string(),
    faixa_etaria = string(),
    sexo = string()
  )
  fields[[category_col]] <- string()
  fields$valor <- int32()
  do.call(schema, fields)
}

make_yearly_chunk <- function(
  aggregated,
  competencia_value,
  municipality,
  categories,
  category_col
) {
  category <- sym(category_col)
  skeleton_values <- list(
    faixa_etaria = age_groups,
    sexo = sexes
  )
  skeleton_values[[category_col]] <- categories
  skeleton <- do.call(expand_grid, skeleton_values)

  existing <- aggregated |>
    filter(
      competencia == competencia_value,
      uf == municipality$uf[[1]],
      ibge == municipality$ibge[[1]]
    ) |>
    select(faixa_etaria, sexo, all_of(category_col), valor)

  skeleton |>
    left_join(existing, by = c("faixa_etaria", "sexo", category_col)) |>
    mutate(
      competencia = competencia_value,
      uf = municipality$uf[[1]],
      ibge = municipality$ibge[[1]],
      municipio = municipality$municipio[[1]],
      valor = as.integer(coalesce(valor, 0))
    ) |>
    arrange(faixa_etaria, sexo, !!category) |>
    select(
      competencia,
      uf,
      ibge,
      municipio,
      faixa_etaria,
      sexo,
      all_of(category_col),
      valor
    )
}

zip_csv_file_atomic <- function(csv_file, zip_path) {
  dir_create(path_dir(zip_path))
  temp_zip <- path_abs(path(path_dir(zip_path), glue(".{path_file(zip_path)}.tmp")))
  temp_dir <- tempfile("sisab_csv_zip_")
  dir_create(temp_dir)
  on.exit(dir_delete(temp_dir), add = TRUE)

  member_name <- sub("\\.zip$", "", path_file(zip_path))
  member_file <- path(temp_dir, member_name)
  file_copy(csv_file, member_file, overwrite = TRUE)

  old_wd <- setwd(temp_dir)
  on.exit(setwd(old_wd), add = TRUE)
  zip_status <- utils::zip(zipfile = temp_zip, files = member_name, flags = "-q")
  setwd(old_wd)
  if (!identical(zip_status, 0L)) {
    stop(glue("Could not create ZIP archive {temp_zip}."), call. = FALSE)
  }
  zip_csv_member(temp_zip, member_name)

  if (!file.rename(temp_zip, zip_path)) {
    stop(glue("Could not move {temp_zip} to {zip_path}."), call. = FALSE)
  }
}

write_completed_yearly_atomic <- function(
  aggregated,
  competencias,
  category_col,
  csv_path,
  parquet_path
) {
  output_schema <- yearly_schema(category_col)
  municipalities <- aggregated |>
    distinct(uf, ibge, municipio) |>
    arrange(uf, ibge)
  categories <- aggregated |>
    distinct(.data[[category_col]]) |>
    arrange(.data[[category_col]]) |>
    pull(.data[[category_col]])

  if (nrow(municipalities) == 0 || length(categories) == 0) {
    stop("No municipality/category combinations found in monthly files.", call. = FALSE)
  }

  dir_create(path_dir(csv_path))
  dir_create(path_dir(parquet_path))
  temp_csv <- path(path_dir(csv_path), glue(".{path_file(csv_path)}.csv.tmp"))
  temp_parquet <- path(path_dir(parquet_path), glue(".{path_file(parquet_path)}.tmp"))

  if (file_exists(temp_csv)) {
    file_delete(temp_csv)
  }
  if (file_exists(temp_parquet)) {
    file_delete(temp_parquet)
  }

  sink <- FileOutputStream$create(temp_parquet)
  properties <- ParquetWriterProperties$create(column_names = output_schema$names)
  writer <- ParquetFileWriter$create(
    output_schema,
    sink,
    properties = properties
  )

  header_written <- FALSE
  for (competencia_value in competencias) {
    for (municipality_index in seq_len(nrow(municipalities))) {
      chunk <- make_yearly_chunk(
        aggregated,
        competencia_value,
        municipalities[municipality_index, ],
        categories,
        category_col
      )
      write_csv2(
        x = chunk,
        file = temp_csv,
        append = header_written,
        col_names = !header_written
      )
      writer$WriteTable(
        Table$create(chunk, schema = output_schema),
        chunk_size = nrow(chunk)
      )
      header_written <- TRUE
    }
  }

  writer$Close()
  sink$close()

  zip_csv_file_atomic(temp_csv, csv_path)
  file_delete(temp_csv)
  if (!file.rename(temp_parquet, parquet_path)) {
    stop(glue("Could not move {temp_parquet} to {parquet_path}."), call. = FALSE)
  }
}

write_csv2_atomic <- function(x, file) {
  dir_create(path_dir(file))
  if (grepl("\\.csv\\.zip$", path_file(file))) {
    temp_file <- path(path_dir(file), glue(".{path_file(file)}.csv.tmp"))
    write_csv2(x = x, file = temp_file)
    zip_csv_file_atomic(temp_file, file)
    file_delete(temp_file)
    return(invisible(file))
  }

  temp_file <- path(path_dir(file), glue(".{path_file(file)}.tmp"))
  write_csv2(x = x, file = temp_file)
  if (!file.rename(temp_file, file)) {
    stop(glue("Could not move {temp_file} to {file}."), call. = FALSE)
  }
  invisible(file)
}

write_parquet_atomic <- function(x, file) {
  dir_create(path_dir(file))
  temp_file <- path(path_dir(file), glue(".{path_file(file)}.tmp"))
  write_parquet(x = x, sink = temp_file)
  if (!file.rename(temp_file, file)) {
    stop(glue("Could not move {temp_file} to {file}."), call. = FALSE)
  }
}

merge_dataset <- function(
  config,
  year,
  data_dir = "data",
  allow_month_gaps = FALSE
) {
  folder <- config$folder
  category_col <- config$category_col
  file_prefix <- config$file_prefix
  dataset_dir <- path(data_dir, folder)

  message(glue("[{file_prefix}] Listing monthly files for {year}..."))
  files <- list_monthly_files(data_dir, folder, file_prefix, year)
  if (length(files) == 0) {
    stop(
      glue("No monthly files found for {file_prefix} {year}."),
      call. = FALSE
    )
  }

  competencias <- validate_months(files, allow_month_gaps)
  message(glue("[{file_prefix}] Reading and summarising {length(files)} monthly file(s)..."))
  aggregated <- read_and_summarise_monthly_files(files, category_col)

  csv_path <- path(dataset_dir, "yearly", glue("{file_prefix}_{year}.csv.zip"))
  parquet_path <- path(
    dataset_dir,
    "yearly",
    glue("{file_prefix}_{year}.parquet")
  )

  message(glue(
    "[{file_prefix}] Completing and writing {csv_path} and {parquet_path}..."
  ))
  write_completed_yearly_atomic(
    aggregated,
    competencias,
    category_col,
    csv_path,
    parquet_path
  )

  invisible(aggregated)
}

main <- function(args = commandArgs(trailingOnly = TRUE)) {
  options <- parse_args(args)
  message(glue("Merging SISAB monthly files for {options$year}."))

  for (row_index in seq_len(nrow(datasets))) {
    merge_dataset(
      datasets[row_index, ],
      year = options$year,
      data_dir = options$data_dir,
      allow_month_gaps = options$allow_month_gaps
    )
  }

  message("Done.")
}

if (sys.nframe() == 0) {
  main()
}
