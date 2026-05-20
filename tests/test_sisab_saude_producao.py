import unittest
from pathlib import Path

from scripts.sisab_saude_producao import (
    SisabError,
    State,
    default_output_path,
    expand_competencias,
    parse_sisab_csv,
    parse_br_integer,
    sort_tidy_rows,
    state_output_label,
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

    def test_parse_br_integer_handles_empty_dash_and_thousands(self) -> None:
        self.assertEqual(parse_br_integer(None), 0)
        self.assertEqual(parse_br_integer(""), 0)
        self.assertEqual(parse_br_integer("-"), 0)
        self.assertEqual(parse_br_integer("1.234"), 1234)

    def test_parse_sisab_csv_rejects_wrong_uf(self) -> None:
        with self.assertRaises(SisabError):
            parse_sisab_csv(SISAB_CSV, "202604", "SP")

    def test_parse_sisab_csv_rejects_missing_header(self) -> None:
        with self.assertRaises(SisabError):
            parse_sisab_csv("metadata only\nno table here\n", "202604", "AC")

    def test_validate_rows_accepts_complete_chunk(self) -> None:
        rows = parse_sisab_csv(SISAB_CSV, "202604", "AC")

        validate_rows(rows, {"120001", "120005"}, State("12", "AC"), "202604")

    def test_validate_rows_rejects_missing_municipality(self) -> None:
        rows = parse_sisab_csv(SISAB_CSV, "202604", "AC")

        with self.assertRaises(SisabError):
            validate_rows(rows, {"120001", "120005", "120010"}, State("12", "AC"), "202604")

    def test_validate_rows_rejects_incomplete_categories(self) -> None:
        rows = parse_sisab_csv(
            "Uf;Ibge;Municipio;Atendimento Individual;Procedimento;Visita Domiciliar;\n"
            "AC;120001;ACRELÂNDIA;1;2;3;\n",
            "202604",
            "AC",
        )

        with self.assertRaises(SisabError):
            validate_rows(rows, {"120001"}, State("12", "AC"), "202604")

    def test_sort_tidy_rows_is_stable_for_output(self) -> None:
        rows = [
            {"competencia": "202604", "uf": "SP", "ibge": "2", "municipio": "B", "tipo_producao": "Z", "valor": 1},
            {"competencia": "202603", "uf": "AC", "ibge": "1", "municipio": "A", "tipo_producao": "A", "valor": 1},
        ]

        sorted_rows = sort_tidy_rows(rows)

        self.assertEqual(sorted_rows[0]["competencia"], "202603")
        self.assertEqual(sorted_rows[1]["ibge"], "2")

    def test_state_output_label_and_default_output_path(self) -> None:
        states = [State("12", "AC"), State("35", "SP")]

        self.assertEqual(state_output_label(states), "AC_SP")
        self.assertEqual(
            str(default_output_path(Path("out"), "202604", states)),
            "out/sisab_saude_producao_202604_AC_SP.csv",
        )

    def test_expand_competencias_accepts_single_month(self) -> None:
        self.assertEqual(expand_competencias(["202604"]), ["202604"])

    def test_expand_competencias_returns_inclusive_month_range(self) -> None:
        self.assertEqual(
            expand_competencias(["202511", "202602"]),
            ["202511", "202512", "202601", "202602"],
        )

    def test_expand_competencias_rejects_reverse_range(self) -> None:
        with self.assertRaises(Exception):
            expand_competencias(["202604", "202601"])


if __name__ == "__main__":
    unittest.main()
