import tempfile
import unittest
from pathlib import Path

from src.repo_gitignore import (
    AUTO_END,
    AUTO_START,
    filing_root_gitignore_patterns,
    sync_filings_gitignore,
)
from src.paths import PROJECT_ROOT


class RepoGitignoreTestCase(unittest.TestCase):
    def test_repo_root_filings_add_ticker_patterns(self):
        patterns = filing_root_gitignore_patterns(PROJECT_ROOT, ["goog", "MSFT"])
        self.assertEqual(patterns, ["GOOG/", "MSFT/"])

    def test_data_filings_root_uses_parent_pattern(self):
        patterns = filing_root_gitignore_patterns(
            PROJECT_ROOT / "data" / "filings",
            ["GOOG"],
        )
        self.assertEqual(patterns, ["data/filings/"])

    def test_outside_repo_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            patterns = filing_root_gitignore_patterns(Path(tmp), ["MSFT"])
        self.assertEqual(patterns, [])

    def test_sync_appends_auto_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            gitignore = repo / ".gitignore"
            gitignore.write_text(".env\n", encoding="utf-8")

            changed = sync_filings_gitignore(
                repo,
                ["AAPL"],
                project_root=repo,
                gitignore_path=gitignore,
            )
            self.assertTrue(changed)
            text = gitignore.read_text(encoding="utf-8")
            self.assertIn(AUTO_START, text)
            self.assertIn("AAPL/", text)
            self.assertIn(AUTO_END, text)

            changed_again = sync_filings_gitignore(
                repo,
                ["AAPL"],
                project_root=repo,
                gitignore_path=gitignore,
            )
            self.assertFalse(changed_again)

    def test_sync_merges_new_tickers(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            gitignore = repo / ".gitignore"
            gitignore.write_text(
                "\n".join([AUTO_START, "AMZN/", AUTO_END, ""]) + "\n",
                encoding="utf-8",
            )

            sync_filings_gitignore(
                repo,
                ["MSFT"],
                project_root=repo,
                gitignore_path=gitignore,
            )
            lines = [
                line.strip()
                for line in gitignore.read_text(encoding="utf-8").splitlines()
                if line.strip() and line.strip() not in {AUTO_START, AUTO_END}
            ]
            self.assertEqual(lines, ["AMZN/", "MSFT/"])


if __name__ == "__main__":
    unittest.main()
