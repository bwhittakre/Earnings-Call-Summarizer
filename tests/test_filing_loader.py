import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from src.ingest.filings import FilingLoadError, dry_run_report, load_filing_packages
from src.ingest.filings.loader import build_filing_package
from src.ingest.filings.types import DocumentType

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "filings"


class FilingLoaderTestCase(unittest.TestCase):
    def test_load_q1_q3_package(self):
        packages = load_filing_packages(
            FIXTURES_ROOT,
            companies="NVDA",
            quarter="FY2025-Q2",
        )
        self.assertEqual(len(packages), 1)
        package = packages[0]
        self.assertEqual(package.ticker, "NVDA")
        self.assertEqual(package.quarter, "FY2025-Q2")
        self.assertFalse(package.is_q4)
        self.assertEqual(package.company_name, "Nvidia")
        self.assertEqual(package.as_of_date, date(2024, 8, 28))
        self.assertIn("=== 10-Q (FY2025-Q2) ===", package.corpus_text)
        self.assertIn("=== 8-K ===", package.corpus_text)
        self.assertGreater(len(package.corpus_text), 50)

    def test_load_q4_package_includes_prior_ten_q(self):
        packages = load_filing_packages(
            FIXTURES_ROOT,
            companies="NVDA",
            quarter="FY2025-Q4",
        )
        package = packages[0]
        self.assertTrue(package.is_q4)
        self.assertIn("=== 10-K (FY2025-Q4) ===", package.corpus_text)
        self.assertIn("=== 10-Q (FY2025-Q1) ===", package.corpus_text)
        self.assertIn("=== 10-Q (FY2025-Q3) ===", package.corpus_text)

    def test_dry_run_report_ok(self):
        report = dry_run_report(
            FIXTURES_ROOT,
            companies="NVDA",
            quarter="FY2025-Q2",
        )
        self.assertIn("Validation: OK", report)
        self.assertIn("NVDA FY2025-Q2", report)
        self.assertIn("raw_corpus_chars=", report)
        self.assertIn("analysis_corpus_chars=", report)

    def test_missing_ticker_raises(self):
        with self.assertRaises(FilingLoadError):
            load_filing_packages(
                FIXTURES_ROOT,
                companies="MISSING",
                quarter="FY2025-Q2",
            )

    def test_load_multiple_eight_k_files(self):
        with TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir) / "NVDA" / "FY2026-Q1"
            folder.mkdir(parents=True)
            ticker_root = folder.parent.parent
            (folder / "10-Q.txt").write_text("Quarterly filing.", encoding="utf-8")
            (folder / "8-K.txt").write_text("Primary 8-K.", encoding="utf-8")
            (folder / "8-K_2025-05-28.txt").write_text("Extra 8-K.", encoding="utf-8")
            package = build_filing_package(
                ticker="NVDA",
                quarter="FY2026-Q1",
                folder=folder,
                ticker_root=ticker_root,
            )
            self.assertEqual(
                sum(
                    1
                    for doc in package.documents.values()
                    if doc.doc_type == DocumentType.EIGHT_K
                ),
                2,
            )
            self.assertIn("=== 8-K ===", package.corpus_text)
            self.assertIn("=== 8-K (2025-05-28) ===", package.corpus_text)

    def test_require_as_of_date_enforced(self):
        with TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir) / "TEST" / "2025-Q1"
            folder.mkdir(parents=True)
            ticker_root = folder.parent
            (folder / "10-Q.txt").write_text("Minimal filing text.", encoding="utf-8")
            with self.assertRaises(FilingLoadError):
                build_filing_package(
                    ticker="TEST",
                    quarter="2025-Q1",
                    folder=folder,
                    ticker_root=ticker_root,
                    require_as_of_date=True,
                )


if __name__ == "__main__":
    unittest.main()
