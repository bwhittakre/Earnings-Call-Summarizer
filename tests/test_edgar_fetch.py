import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from src.ingest.edgar.config import EdgarConfig
from src.ingest.edgar.models import EdgarFetchError, FetchedDocument
from src.ingest.edgar.period import expected_period_end_date, manifest_as_of_date_text
from src.ingest.edgar.resolver import next_quarter_label
from src.ingest.edgar.selector import build_quarter_fetch_plan
from src.ingest.edgar.writer import write_quarter_package

FIXTURES = Path(__file__).parent / "fixtures" / "edgar"


class FakeEdgarClient:
    def __init__(self, submissions: dict, *, eight_k_text: str):
        self.submissions = submissions
        self.eight_k_text = eight_k_text
        self.config = EdgarConfig(
            user_agent="Test Agent",
            rate_limit_rps=100,
            earnings_8k_window_days=45,
            company_folders={"AMZN": "Amazon"},
            company_names={"AMZN": "Amazon"},
        )

    def fetch_submissions(self, cik: int) -> dict:
        return self.submissions

    def fetch_submissions_file(self, filename: str) -> dict:
        raise EdgarFetchError("not used in fixture")

    def filing_document_url(self, cik: int, accession_number: str, primary_document: str) -> str:
        return f"https://example.test/{accession_number}/{primary_document}"

    def fetch_filing_document(self, cik: int, accession_number: str, primary_document: str) -> str:
        if primary_document.endswith("8k.htm"):
            return self.eight_k_text
        return "Revenue grew 24% year over year in the third quarter."


class EdgarPeriodTestCase(unittest.TestCase):
    def test_amzn_fy2019_q3_period_end(self):
        self.assertEqual(
            expected_period_end_date("AMZN", "FY2019-Q3"),
            date(2018, 9, 30),
        )
        self.assertEqual(
            manifest_as_of_date_text("AMZN", "FY2019-Q3"),
            "(09,30,2018)",
        )

    def test_nvda_fy2026_q1_period_end(self):
        end = expected_period_end_date("NVDA", "FY2026-Q1")
        self.assertEqual(end.year, 2025)
        self.assertEqual(end.month, 4)
        self.assertEqual(end.weekday(), 6)


class EdgarSelectorTestCase(unittest.TestCase):
    def test_build_amzn_fy2019_q3_plan(self):
        submissions = json.loads(
            (FIXTURES / "amzn_fy2019_q3_submissions.json").read_text(encoding="utf-8")
        )
        client = FakeEdgarClient(
            submissions,
            eight_k_text="Item 2.02 Results of Operations and Financial Condition",
        )
        with tempfile.TemporaryDirectory() as tmp:
            plan = build_quarter_fetch_plan(
                ticker="AMZN",
                quarter="FY2019-Q3",
                filings_root=Path(tmp),
                config=client.config,
                client=client,
                submissions=submissions,
                cik=1018724,
            )
            self.assertEqual(plan.quarter, "FY2019-Q3")
            self.assertEqual(plan.as_of_date_text, "(09,30,2018)")
            filenames = {doc.filename for doc in plan.documents}
            self.assertEqual(filenames, {"10-Q.txt", "8-K.txt"})
            ten_q = next(doc for doc in plan.documents if doc.filename == "10-Q.txt")
            self.assertEqual(ten_q.filing.accession_number, "0001018724-19-000120")


class EdgarWriterTestCase(unittest.TestCase):
    def test_write_manifest_and_documents(self):
        submissions = json.loads(
            (FIXTURES / "amzn_fy2019_q3_submissions.json").read_text(encoding="utf-8")
        )
        client = FakeEdgarClient(
            submissions,
            eight_k_text="Item 2.02 Results of Operations and Financial Condition",
        )
        with tempfile.TemporaryDirectory() as tmp:
            filings_root = Path(tmp)
            plan = build_quarter_fetch_plan(
                ticker="AMZN",
                quarter="FY2019-Q3",
                filings_root=filings_root,
                config=client.config,
                client=client,
                submissions=submissions,
                cik=1018724,
            )
            fetched = [
                FetchedDocument(
                    doc_type=doc.doc_type,
                    filename=doc.filename,
                    filing=doc.filing,
                    text="Sample filing text for validation.",
                    char_count=34,
                )
                for doc in plan.documents
            ]
            folder = write_quarter_package(plan, fetched)
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["ticker"], "AMZN")
            self.assertEqual(manifest["quarter"], "FY2019-Q3")
            self.assertEqual(len(manifest["documents"]), 2)
            self.assertTrue((folder / "10-Q.txt").is_file())
            self.assertTrue((folder / "8-K.txt").is_file())


class EdgarResolverTestCase(unittest.TestCase):
    def test_next_quarter_label(self):
        self.assertEqual(next_quarter_label("FY2019-Q3"), "FY2019-Q4")
        self.assertEqual(next_quarter_label("FY2019-Q4"), "FY2020-Q1")


if __name__ == "__main__":
    unittest.main()
