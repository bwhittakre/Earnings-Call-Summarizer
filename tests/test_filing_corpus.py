import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.ingest.filings.corpus import (
    TRUNCATION_MARKER,
    build_tagged_corpus,
    discover_eight_k_paths,
    find_document_path,
    load_document,
    load_eight_k_documents,
    section_tag,
    truncate_corpus_for_llm,
)
from src.ingest.filings.types import DocumentType, LoadedDocument


class FilingCorpusTestCase(unittest.TestCase):
    def test_section_tag(self):
        self.assertEqual(section_tag(DocumentType.TEN_Q, "FY2025-Q2"), "10-Q (FY2025-Q2)")
        self.assertEqual(section_tag(DocumentType.TEN_K, "FY2025-Q4"), "10-K (FY2025-Q4)")
        self.assertEqual(section_tag(DocumentType.EIGHT_K), "8-K")
        self.assertEqual(
            section_tag(DocumentType.EIGHT_K, section_label="2025-05-28"),
            "8-K (2025-05-28)",
        )
        self.assertEqual(section_tag(DocumentType.PRESS_RELEASE), "PRESS_RELEASE")

    def test_load_multiple_eight_k_documents(self):
        with TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            (folder / "8-K.txt").write_text("Primary 8-K filing body.", encoding="utf-8")
            (folder / "8-K_2025-05-28.txt").write_text(
                "Secondary 8-K filing body.",
                encoding="utf-8",
            )
            subfolder = folder / "8-K"
            subfolder.mkdir()
            (subfolder / "item_5_02.txt").write_text(
                "Officer change 8-K body.",
                encoding="utf-8",
            )

            paths = discover_eight_k_paths(folder)
            self.assertEqual(len(paths), 3)

            documents = load_eight_k_documents(folder)
            corpus = build_tagged_corpus(documents)
            self.assertIn("=== 8-K ===", corpus)
            self.assertIn("=== 8-K (2025-05-28) ===", corpus)
            self.assertIn("=== 8-K (item 5 02) ===", corpus)
            self.assertIn("Primary 8-K filing body.", corpus)
            self.assertIn("Secondary 8-K filing body.", corpus)
            self.assertIn("Officer change 8-K body.", corpus)

    def test_build_tagged_corpus(self):
        documents = [
            LoadedDocument(
                doc_type=DocumentType.TEN_Q,
                quarter_label="FY2025-Q2",
                path=Path("10-Q.txt"),
                text="Quarterly filing body.",
            ),
            LoadedDocument(
                doc_type=DocumentType.EIGHT_K,
                quarter_label=None,
                path=Path("8-K.txt"),
                text="Event filing body.",
            ),
        ]
        corpus = build_tagged_corpus(documents)
        self.assertIn("=== 10-Q (FY2025-Q2) ===", corpus)
        self.assertIn("Quarterly filing body.", corpus)
        self.assertIn("=== 8-K ===", corpus)
        self.assertIn("Event filing body.", corpus)

    def test_truncate_corpus_keeps_small_sections_and_caps_large(self):
        documents = [
            LoadedDocument(
                doc_type=DocumentType.TEN_Q,
                quarter_label="FY2026-Q1",
                path=Path("10-Q.txt"),
                text="Q" * 50_000,
            ),
            LoadedDocument(
                doc_type=DocumentType.EIGHT_K,
                quarter_label=None,
                path=Path("8-K.txt"),
                text="Event filing body.",
            ),
        ]
        corpus = build_tagged_corpus(documents)
        truncated, warnings = truncate_corpus_for_llm(corpus, max_chars=5_000)

        self.assertTrue(warnings)
        self.assertLessEqual(len(truncated), 5_000)
        self.assertIn("Event filing body.", truncated)
        self.assertIn(TRUNCATION_MARKER, truncated)

    def test_find_document_path_and_load(self):
        with TemporaryDirectory() as tmp_dir:
            folder = Path(tmp_dir)
            doc_path = folder / "10-Q.txt"
            doc_path.write_text("Sample 10-Q content for testing.", encoding="utf-8")

            found = find_document_path(folder, ("10-Q", "10-q"))
            self.assertEqual(found, doc_path)

            loaded = load_document(folder, DocumentType.TEN_Q, quarter_label="FY2025-Q2")
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.doc_type, DocumentType.TEN_Q)
            self.assertEqual(loaded.quarter_label, "FY2025-Q2")
            self.assertIn("Sample 10-Q content", loaded.text)


if __name__ == "__main__":
    unittest.main()
