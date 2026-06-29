import unittest

from src.ingest.documents.fetch.html_text import html_to_text
from src.validation.evidence_validator import excerpt_found_in_source


NVDA_TABLE_SNIPPET = """
<html><body>
<p>Revenue grew strongly across data center.</p>
<table>
<tr><th>Segment</th><th>Revenue</th></tr>
<tr><td>Data Center</td><td>$26.3 billion</td></tr>
<tr><td>Gaming</td><td>$2.9 billion</td></tr>
</table>
</body></html>
"""


class HtmlTableExtractTestCase(unittest.TestCase):
    def test_table_rows_preserved_for_verbatim_validation(self):
        text = html_to_text(NVDA_TABLE_SNIPPET)
        self.assertIn("Data Center | $26.3 billion", text)
        row_excerpt = "Data Center | $26.3 billion"
        self.assertTrue(
            excerpt_found_in_source(row_excerpt, text),
            "table row text must survive extraction for validation",
        )

    def test_table_pipe_format_is_contiguous_substring(self):
        text = html_to_text(NVDA_TABLE_SNIPPET)
        excerpt = "Segment | Revenue\nData Center | $26.3 billion"
        self.assertTrue(excerpt_found_in_source(excerpt, text))


if __name__ == "__main__":
    unittest.main()
