import unittest
from pathlib import Path

from src.ingest.filings.excerpt_puller import (
    pull_excerpts,
    pull_excerpts_from_document,
    score_paragraph,
    split_paragraphs,
)
from src.ingest.filings.loader import ExcerptConfig, build_filing_package, load_filing_packages
from src.ingest.filings.sec_sanitize import sanitize_filing_text
from src.ingest.filings.sec_sections import extract_sections, select_sections_for_doc
from src.ingest.filings.types import DocumentType, LoadedDocument

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "filings"
BLOATED_10Q = Path(__file__).parent / "fixtures" / "bloated_10q.txt"


class SecSanitizeTestCase(unittest.TestCase):
    def test_sanitize_strips_edgar_html_and_xbrl_noise(self):
        raw = BLOATED_10Q.read_text(encoding="utf-8")
        sanitized = sanitize_filing_text(raw)
        self.assertLess(len(sanitized), len(raw))
        self.assertNotIn("xbrli:shares", sanitized)
        self.assertNotIn("<html>", sanitized)
        self.assertIn("Revenue grew 78% year over year", sanitized)


class SecSectionsTestCase(unittest.TestCase):
    def test_extract_10q_items(self):
        sanitized = sanitize_filing_text(BLOATED_10Q.read_text(encoding="utf-8"))
        sections = extract_sections(sanitized, DocumentType.TEN_Q)
        item_ids = {section.item_id for section in sections}
        self.assertIn("2", item_ids)
        self.assertIn("1A", item_ids)

    def test_select_sections_prefers_mda_and_risk(self):
        sanitized = sanitize_filing_text(BLOATED_10Q.read_text(encoding="utf-8"))
        picked = select_sections_for_doc(sanitized, DocumentType.TEN_Q)
        item_ids = {section.item_id for section in picked}
        self.assertIn("2", item_ids)


class ExcerptPullerTestCase(unittest.TestCase):
    def test_score_paragraph_prefers_guidance_over_boilerplate(self):
        guidance = score_paragraph(
            "We expect first quarter revenue of $43.0 billion, plus or minus 2%."
        )
        boilerplate = score_paragraph(
            "Forward-looking statements involve risks and uncertainties."
        )
        self.assertGreater(guidance, boilerplate)

    def test_pull_excerpts_from_bloated_document(self):
        sanitized = sanitize_filing_text(BLOATED_10Q.read_text(encoding="utf-8"))
        doc = LoadedDocument(
            doc_type=DocumentType.TEN_Q,
            quarter_label="FY2026-Q1",
            path=Path("10-Q.txt"),
            text=sanitized,
        )
        result = pull_excerpts_from_document(
            doc,
            budget=50_000,
            primary_quarter="FY2026-Q1",
        )
        self.assertGreater(result.excerpt_count, 0)
        self.assertLess(result.excerpt_chars, result.raw_chars)
        combined = "\n".join(result.excerpts)
        self.assertIn("Revenue grew 78% year over year", combined)
        for excerpt in result.excerpts:
            self.assertIn(excerpt, sanitized)

    def test_small_fixture_passes_through_most_content(self):
        packages = load_filing_packages(
            FIXTURES_ROOT,
            companies="NVDA",
            quarter="FY2025-Q2",
            excerpt_config=ExcerptConfig(mode="smart"),
        )
        package = packages[0]
        self.assertGreater(len(package.analysis_corpus_text), 50)
        self.assertLessEqual(
            len(package.analysis_corpus_text),
            len(package.raw_corpus_text) + 500,
        )

    def test_full_mode_keeps_entire_corpus(self):
        packages = load_filing_packages(
            FIXTURES_ROOT,
            companies="NVDA",
            quarter="FY2025-Q2",
            excerpt_config=ExcerptConfig(mode="full"),
        )
        package = packages[0]
        self.assertEqual(
            len(package.analysis_corpus_text),
            len(package.raw_corpus_text),
        )

    def test_split_paragraphs_skips_short_lines(self):
        paragraphs = split_paragraphs("short\n\n" + ("long paragraph " * 10))
        self.assertEqual(len(paragraphs), 1)


class ExcerptLoaderIntegrationTestCase(unittest.TestCase):
    def test_build_package_with_bloated_10q(self):
        with __import__("tempfile").TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir) / "NVDA" / "FY2026-Q1"
            folder.mkdir(parents=True)
            ticker_root = folder.parent.parent
            (folder / "10-Q.txt").write_text(
                BLOATED_10Q.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (folder / "8-K.txt").write_text(
                "Revenue for the quarter was $39.3 billion.",
                encoding="utf-8",
            )
            package = build_filing_package(
                ticker="NVDA",
                quarter="FY2026-Q1",
                folder=folder,
                ticker_root=ticker_root,
                excerpt_config=ExcerptConfig(mode="smart", max_analysis_chars=50_000),
            )
            self.assertLess(
                len(package.analysis_corpus_text),
                len(package.raw_corpus_text),
            )
            self.assertIn("=== 8-K ===", package.analysis_corpus_text)
            self.assertGreater(package.excerpt_stats["excerpt_count"], 0)


if __name__ == "__main__":
    unittest.main()
