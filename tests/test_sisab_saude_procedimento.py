import unittest
from pathlib import Path

from scripts.sisab_saude_procedimento import (
    default_output_path,
    parse_sisab_csv,
    sort_tidy_rows,
    validate_rows,
)
from scripts.sisab_saude_producao import SisabError


SISAB_PROCEDIMENTO_CSV = """Secretaria de Atenção Primária à Saúde - SAPS/MS
Dados sujeitos à alteração
Uf;Ibge;Municipio;Aferição de PA;Curativo simples;
AC;120001;ACRELÂNDIA;1.234;-;
AC;120005;ASSIS BRASIL;2;3;
SP;350010;ADAMANTINA;4;5;
"""


class SisabProcedimentoParserTest(unittest.TestCase):
    def test_parse_sisab_csv_returns_tidy_procedimento_rows(self) -> None:
        rows = parse_sisab_csv(SISAB_PROCEDIMENTO_CSV, "202604", "De 30 a 34 anos", "Masculino")

        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[0]["competencia"], "202604")
        self.assertEqual(rows[0]["uf"], "AC")
        self.assertEqual(rows[0]["ibge"], "120001")
        self.assertEqual(rows[0]["faixa_etaria"], "De 30 a 34 anos")
        self.assertEqual(rows[0]["sexo"], "Masculino")
        self.assertEqual(rows[0]["procedimento"], "Aferição de PA")
        self.assertEqual(rows[0]["valor"], 1234)
        self.assertEqual(rows[1]["valor"], 0)

    def test_parse_sisab_csv_rejects_missing_header(self) -> None:
        with self.assertRaises(SisabError):
            parse_sisab_csv("metadata only\n", "202604")

    def test_validate_rows_accepts_brazil_csv(self) -> None:
        rows = parse_sisab_csv(SISAB_PROCEDIMENTO_CSV, "202604", "De 30 a 34 anos", "Masculino")
        validate_rows(rows, "202604")

    def test_sort_tidy_rows_is_stable_for_output(self) -> None:
        rows = [
            {"competencia": "202604", "uf": "AC", "ibge": "2", "municipio": "B", "faixa_etaria": "De 5 a 9 anos", "sexo": "Masculino", "procedimento": "Z", "valor": 1},
            {"competencia": "202603", "uf": "AC", "ibge": "1", "municipio": "A", "faixa_etaria": "De 1 a 4 anos", "sexo": "Feminino", "procedimento": "A", "valor": 1},
        ]

        sorted_rows = sort_tidy_rows(rows)

        self.assertEqual(sorted_rows[0]["competencia"], "202603")
        self.assertEqual(sorted_rows[1]["ibge"], "2")

    def test_default_output_path_is_per_competencia(self) -> None:
        path = default_output_path(Path("out"), "202604")

        self.assertEqual(str(path), "out/sisab_saude_procedimento_202604.csv.zip")


if __name__ == "__main__":
    unittest.main()
