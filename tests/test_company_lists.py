import tempfile
import unittest
from pathlib import Path

from src.ingest.company_lists import (
    CompanyListError,
    format_companies_csv,
    list_available_sectors,
    load_companies_file,
    load_sector_companies,
    parse_company_list_text,
    resolve_companies_argument,
    resolve_sector_file,
)
from src.paths import PROJECT_ROOT


class CompanyListsTestCase(unittest.TestCase):
    def test_parse_company_list_text_skips_comments_and_blanks(self):
        text = """
        # header
        MSFT
        AMZN  # inline comment

        NVDA
        MSFT
        """
        self.assertEqual(parse_company_list_text(text), ["MSFT", "AMZN", "NVDA"])

    def test_parse_company_list_text_rejects_empty(self):
        with self.assertRaises(CompanyListError):
            parse_company_list_text("# only comments\n")

    def test_load_companies_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "list.txt"
            path.write_text("MSFT\nTSLA\n", encoding="utf-8")
            self.assertEqual(load_companies_file(path), ["MSFT", "TSLA"])

    def test_resolve_sector_file(self):
        path = resolve_sector_file("mega_cap_tech")
        self.assertEqual(path.name, "mega_cap_tech.txt")
        self.assertTrue(path.is_file())

    def test_resolve_sector_file_unknown(self):
        with self.assertRaises(CompanyListError):
            resolve_sector_file("not_a_real_sector_name")

    def test_load_sector_companies(self):
        entries = load_sector_companies("semiconductors")
        self.assertIn("NVDA", entries)
        self.assertIn("AMD", entries)

    def test_list_available_sectors(self):
        sectors = list_available_sectors()
        self.assertIn("mega_cap_tech", sectors)
        self.assertIn("semiconductors", sectors)

    def test_resolve_companies_argument_requires_one_source(self):
        with self.assertRaises(CompanyListError):
            resolve_companies_argument()
        with self.assertRaises(CompanyListError):
            resolve_companies_argument(companies="MSFT", sector="mega_cap_tech")

    def test_resolve_companies_argument_from_sector(self):
        resolved = resolve_companies_argument(sector="mega_cap_tech")
        self.assertEqual(resolved.split(","), load_sector_companies("mega_cap_tech"))

    def test_resolve_companies_argument_from_file(self):
        fixture = PROJECT_ROOT / "config" / "sectors" / "mega_cap_tech.txt"
        resolved = resolve_companies_argument(companies_file=str(fixture))
        self.assertEqual(resolved, format_companies_csv(load_companies_file(fixture)))


if __name__ == "__main__":
    unittest.main()
