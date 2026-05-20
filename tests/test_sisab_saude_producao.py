import unittest

from scripts.sisab_saude_producao import (
    SisabError,
    State,
    parse_sisab_csv,
    validate_rows,
)


SISAB_CSV = """Secretaria de Atenção Primária à Saúde - SAPS/MS
Dados sujeitos à alteração
---Descrição dos Filtros Utilizados---
Competência: ABR/2026.
Uf;Ibge;Municipio;Atendimento Individual;Atendimento Odontológico;Procedimento;Visita Domiciliar;
AC;120001;ACRELÂNDIA;1.234;56;0;789;
AC;120005;ASSIS BRASIL;2;3;4;5;
"""


class SisabParserTest(unittest.TestCase):
    def test_parse_sisab_csv_returns_tidy_rows(self) -> None:
        rows = parse_sisab_csv(SISAB_CSV, "202604", "AC")

        self.assertEqual(len(rows), 8)
        self.assertEqual(rows[0]["competencia"], "202604")
        self.assertEqual(rows[0]["uf"], "AC")
        self.assertEqual(rows[0]["ibge"], "120001")
        self.assertEqual(rows[0]["tipo_producao"], "Atendimento Individual")
        self.assertEqual(rows[0]["valor"], 1234)
        self.assertNotIn("", {row["tipo_producao"] for row in rows})

    def test_validate_rows_accepts_complete_chunk(self) -> None:
        rows = parse_sisab_csv(SISAB_CSV, "202604", "AC")

        validate_rows(rows, {"120001", "120005"}, State("12", "AC"), "202604")

    def test_validate_rows_rejects_missing_municipality(self) -> None:
        rows = parse_sisab_csv(SISAB_CSV, "202604", "AC")

        with self.assertRaises(SisabError):
            validate_rows(rows, {"120001", "120005", "120010"}, State("12", "AC"), "202604")


if __name__ == "__main__":
    unittest.main()
