"""SEC EDGAR fallback for earnings material.

ROIC.ai is the primary transcript source. When it has no transcript for a
company (404) or the period is outside the free-tier history window (403), fall
back to the company's most recent earnings 8-K (Item 2.02, "Results of
Operations") on SEC EDGAR and pull the earnings press-release / prepared-remarks
exhibit (typically EX-99.1).

CAVEAT: EDGAR 8-K exhibits reliably carry the earnings press release and often
prepared remarks, but usually NOT the live analyst Q&A. Treat this as a coverage
backstop, not a transcript-quality equivalent.

EDGAR requires a descriptive User-Agent with a contact email (config.SEC_USER_AGENT)
and rate-limits abusive clients; see https://www.sec.gov/os/webmaster-faq#developers.
"""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

from . import config

_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
_ARCHIVE_DIR_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/"

_EARNINGS_ITEM = "2.02"  # Item 2.02 — Results of Operations and Financial Condition

_ticker_to_cik: dict[str, str] | None = None


class EdgarError(RuntimeError):
    """A recoverable failure while resolving or fetching from EDGAR."""


@dataclass
class EdgarResult:
    ticker: str
    cik: str
    form: str
    filing_date: str
    accession: str
    source_url: str
    text: str


class _TextExtractor(HTMLParser):
    """Minimal HTML -> text: drops script/style, adds newlines on block tags."""

    _BLOCK = {
        "p", "br", "div", "tr", "table", "li", "ul", "ol",
        "h1", "h2", "h3", "h4", "h5", "h6", "section", "article",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in self._BLOCK:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag in self._BLOCK:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        lines = [ln.strip() for ln in raw.splitlines()]
        out: list[str] = []
        blank = False
        for ln in lines:
            if ln:
                out.append(ln)
                blank = False
            elif not blank:
                out.append("")
                blank = True
        return "\n".join(out).strip()


def _html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return parser.text()


def _client():
    import httpx

    return httpx.Client(
        headers={"User-Agent": config.SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"},
        timeout=60.0,
        follow_redirects=True,
    )


def _load_ticker_map(client: Any) -> dict[str, str]:
    global _ticker_to_cik
    if _ticker_to_cik is not None:
        return _ticker_to_cik
    resp = client.get(_TICKER_MAP_URL)
    if resp.status_code != 200:
        raise EdgarError(f"Could not load SEC ticker map (HTTP {resp.status_code}).")
    mapping: dict[str, str] = {}
    for row in resp.json().values():
        ticker = str(row.get("ticker", "")).upper()
        cik = str(row.get("cik_str", "")).zfill(10)
        if ticker:
            mapping[ticker] = cik
    _ticker_to_cik = mapping
    return mapping


def resolve_cik(ticker: str, client: Any) -> str:
    mapping = _load_ticker_map(client)
    cik = mapping.get(ticker.upper())
    if not cik:
        raise EdgarError(f"No SEC CIK found for ticker {ticker!r}.")
    return cik


def _iter_recent_filings(client: Any, cik10: str):
    resp = client.get(_SUBMISSIONS_URL.format(cik10=cik10))
    if resp.status_code != 200:
        raise EdgarError(f"Could not load EDGAR submissions for CIK {cik10} (HTTP {resp.status_code}).")
    recent = resp.json().get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    for i in range(len(forms)):
        yield {
            "form": forms[i],
            "items": (recent.get("items") or [""] * len(forms))[i],
            "accession": recent.get("accessionNumber", [])[i],
            "filing_date": recent.get("filingDate", [])[i],
            "primary_doc": (recent.get("primaryDocument") or [""] * len(forms))[i],
        }


def _is_ex99(name: str) -> bool:
    """Heuristic: does this filename look like an EX-99.x exhibit?

    The index.json ``type`` field only carries icon names (e.g. ``text.gif``),
    not SEC exhibit types, so we match the filename. Normalizing to alphanumerics
    catches the common shapes: ``a8-kex991q2....htm``, ``d123dex991.htm``,
    ``exhibit99-1.htm`` -> ``ex99`` / ``exhibit99``.
    """
    lower = name.lower()
    if "index" in lower or not lower.endswith((".htm", ".html")):
        return False
    norm = "".join(ch for ch in lower if ch.isalnum())
    return "ex99" in norm or "exhibit99" in norm


def _pick_exhibit(client: Any, dir_url: str, primary_doc: str) -> str:
    """Return the URL of the best earnings exhibit in a filing directory.

    Prefer an EX-99.x exhibit (press release / prepared remarks); fall back to
    the filing's primary document.
    """
    resp = client.get(dir_url + "index.json")
    if resp.status_code == 200:
        names = [str(it.get("name", "")) for it in resp.json().get("directory", {}).get("item", [])]
        for name in names:
            if _is_ex99(name):
                return dir_url + name
    if primary_doc:
        return dir_url + primary_doc
    raise EdgarError(f"No usable exhibit found in {dir_url}")


def fetch_latest_earnings_report(ticker: str) -> EdgarResult:
    """Fetch the most recent earnings 8-K (Item 2.02) exhibit for a ticker.

    Raises ``EdgarError`` if the ticker can't be resolved or no earnings 8-K is
    found in the company's recent filings.
    """
    with _client() as client:
        cik10 = resolve_cik(ticker, client)
        chosen = None
        for f in _iter_recent_filings(client, cik10):
            if f["form"] == "8-K" and _EARNINGS_ITEM in str(f["items"]):
                chosen = f
                break
        if chosen is None:
            raise EdgarError(
                f"No recent earnings 8-K (Item {_EARNINGS_ITEM}) found for {ticker} on EDGAR."
            )

        accession_nodash = chosen["accession"].replace("-", "")
        dir_url = _ARCHIVE_DIR_URL.format(cik=int(cik10), accession_nodash=accession_nodash)
        exhibit_url = _pick_exhibit(client, dir_url, chosen["primary_doc"])

        resp = client.get(exhibit_url)
        if resp.status_code != 200:
            raise EdgarError(f"Could not download exhibit {exhibit_url} (HTTP {resp.status_code}).")

        body = resp.text
        text = _html_to_text(body) if "<" in body and ">" in body else body.strip()
        if not text:
            raise EdgarError(f"Exhibit {exhibit_url} produced no readable text.")

        return EdgarResult(
            ticker=ticker.upper(),
            cik=cik10,
            form=chosen["form"],
            filing_date=chosen["filing_date"],
            accession=chosen["accession"],
            source_url=exhibit_url,
            text=text,
        )
