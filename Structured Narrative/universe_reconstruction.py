#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 0 of the Structured Narrative Expansion plan: point-in-time universe
reconstruction for the Technology Select Sector SPDR Fund (XLK), built
directly from SEC EDGAR regulatory filings -- NOT from a single current
snapshot. A company that was a sector-fund constituent years ago but was
later acquired, delisted, or dropped from the fund must still appear in the
periods it was actually a member; picking today's constituents and projecting
them backward would reintroduce survivorship bias by construction. See
``universe_reference_key.txt`` (written by ``--write-docs``) for the full
methodology writeup.

Data sources, by era (holdings-disclosure format changed over the window):
  - N-PORT-P (~2019-present, quarterly): structured XML, ``<invstOrSec>``
    schema -- one holding per element, with an explicit ``pctVal`` (% of the
    fund's net assets) already computed by the filer.
  - N-Q (pre-2019, filed semi-annually -- Feb/Aug, covering the fiscal Q1/Q3
    of the Sept-30 fiscal year end): narrative HTML filed *jointly* for every
    Select Sector SPDR fund in one document; the Technology fund's own
    "SCHEDULE OF INVESTMENTS" section must be located and sliced out.
  - N-CSR / N-CSRS (annual / semi-annual shareholder reports): same
    joint-filing, narrative-HTML structure as N-Q. Used strictly as a
    **fallback** to fill any quarter N-Q doesn't cover -- per the build plan,
    not a primary source, and the most brittle of the three to parse.

Together, N-Q + N-CSR/N-CSRS give quarterly-to-semiannual point-in-time
resolution before 2019; N-PORT-P gives clean quarterly resolution from 2019
on. Neither gives daily resolution -- see the methodology doc for why that's
an acceptable (and disclosed) limitation for defining a *universe*, as
opposed to a trading signal.

CIK / series / class resolution -- verified directly against SEC EDGAR's own
``primary_doc.xml`` for a live N-PORT-P filing (not inferred from a
third-party site):
  - Filer CIK: 1064641 ("SELECT SECTOR SPDR TRUST" -- the trust files jointly
    for all of its sector funds, so every filing list must be scoped to this
    one series, not just the CIK).
  - Series ID: S000006415 ("State Street(R) Technology Select Sector SPDR(R)
    ETF" -- ticker XLK; State Street's 2023 rebrand of what was previously
    named "The Technology Select Sector SPDR Fund" in older filings).
  - Class ID: C000017601.

EDGAR requires a descriptive User-Agent that identifies the requester with a
contact email (see https://www.sec.gov/os/webmaster-faq#developers) and
rate-limits automated clients to 10 req/sec; override via the SEC_USER_AGENT
env var. This module makes its own HTTP calls (no dependency on the sibling
``earnings-scraper-main`` package) so Structured Narrative's universe
reconstruction has no cross-repo import.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

import os

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "output" / "universe"
RAW_DIR = OUT_DIR / "raw_filings"

# ── Resolved identifiers (see module docstring for how these were verified) ──
TRUST_CIK = "1064641"
TRUST_NAME = "SELECT SECTOR SPDR TRUST"
SERIES_ID = "S000006415"
SERIES_NAME = "State Street(R) Technology Select Sector SPDR(R) ETF"
LEGACY_FUND_NAME = "Technology Select Sector SPDR Fund"
CLASS_ID = "C000017601"
FUND_TICKER = "XLK"

DEFAULT_USER_AGENT = "earnings-scraper (contact: nhirt@cassiuscap.com)"
USER_AGENT = os.environ.get("SEC_USER_AGENT", DEFAULT_USER_AGENT)
HEADERS = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}

_MIN_REQUEST_INTERVAL = 0.15  # stay well under SEC's 10 req/sec cap
_last_request_ts = [0.0]

_MONTHS = (
    "january february march april may june july august september october "
    "november december"
).split()


class UniverseReconstructionError(RuntimeError):
    """Raised for unrecoverable EDGAR fetch/parse failures."""


# ── HTTP plumbing ─────────────────────────────────────────────────────────────


def _get(url: str, *, params: dict | None = None, timeout: float = 30.0, retries: int = 4) -> requests.Response:
    last_exc: Exception | None = None
    for attempt in range(retries):
        elapsed = time.monotonic() - _last_request_ts[0]
        if elapsed < _MIN_REQUEST_INTERVAL:
            time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
        resp = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
        _last_request_ts[0] = time.monotonic()
        if resp.status_code == 200:
            return resp
        if resp.status_code in (429, 503):
            # Transient SEC throttling -- back off and retry rather than fail
            # a whole filing over a momentary rate-limit response.
            backoff = 1.5 * (attempt + 1)
            time.sleep(backoff)
            last_exc = UniverseReconstructionError(f"HTTP {resp.status_code} fetching {url}")
            continue
        raise UniverseReconstructionError(f"HTTP {resp.status_code} fetching {url}")
    raise last_exc or UniverseReconstructionError(f"Failed fetching {url}")


def _cache_path(accession: str, suffix: str) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    return RAW_DIR / f"{accession}.{suffix}"


def _cached_get_text(url: str, accession: str, suffix: str, *, use_cache: bool = True) -> str:
    """Fetch ``url`` as text, caching to ``RAW_DIR`` keyed by accession number.

    Caching serves two purposes: it avoids re-hitting EDGAR on repeat runs, and
    it leaves a durable audit trail of the exact filing bytes each membership
    row was parsed from.
    """
    path = _cache_path(accession, suffix)
    if use_cache and path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    text = _get(url).text
    path.write_text(text, encoding="utf-8")
    return text


# ── Filing discovery ──────────────────────────────────────────────────────────


@dataclass
class FilingRef:
    form_type: str
    filing_date: str  # YYYY-MM-DD, as filed (not the holdings as-of date)
    accession: str
    index_url: str


def list_series_filings(form_types: Iterable[str], *, count: int = 100) -> list[FilingRef]:
    """List every filing of the given form type(s) for the Technology series.

    Scoping ``CIK=S000006415`` (the *series* ID, not the trust's own CIK)
    returns only Technology-fund filings even though the trust files jointly
    for every Select Sector SPDR fund -- confirmed against EDGAR's own
    ``primary_doc.xml`` (``seriesId``/``seriesName`` match) during Phase 0
    scoping.
    """
    refs: list[FilingRef] = []
    for form_type in form_types:
        start = 0
        while True:
            resp = _get(
                "https://www.sec.gov/cgi-bin/browse-edgar",
                params={
                    "action": "getcompany",
                    "CIK": SERIES_ID,
                    "type": form_type,
                    "dateb": "",
                    "owner": "include",
                    "count": str(count),
                    "start": str(start),
                    "output": "atom",
                },
            )
            entries = re.findall(r"<entry>(.*?)</entry>", resp.text, re.S)
            if not entries:
                break
            for entry in entries:
                dt = re.search(r"<filing-date>(.*?)</filing-date>", entry)
                acc = re.search(r"<accession-number>(.*?)</accession-number>", entry)
                href = re.search(r"<filing-href>(.*?)</filing-href>", entry)
                cat = re.search(r'term="([^"]+)"', entry)
                if not (dt and acc and href):
                    continue
                refs.append(
                    FilingRef(
                        form_type=(cat.group(1) if cat else form_type),
                        filing_date=dt.group(1),
                        accession=acc.group(1),
                        index_url=href.group(1),
                    )
                )
            if len(entries) < count:
                break
            start += count
    refs.sort(key=lambda r: r.filing_date)
    return refs


def _index_documents(index_url: str, accession: str) -> list[str]:
    text = _cached_get_text(index_url, accession + "_index", "htm")
    accession_nodash = accession.replace("-", "")
    hrefs = re.findall(r'href="([^"]+)"', text)
    return [h for h in hrefs if accession_nodash in h]


# ── N-PORT-P parsing (2019+, structured XML) ─────────────────────────────────


@dataclass
class Holding:
    report_date: date
    source_form: str
    accession: str
    raw_name: str
    cusip: str | None
    isin: str | None
    shares_or_balance: float | None
    value_usd: float | None
    pct_of_fund: float | None
    pct_basis: str  # "disclosed" (N-PORT pctVal) or "computed" (legacy: value / section total)


def _parse_nport_xml(xml_text: str, *, source_form: str, accession: str) -> list[Holding]:
    gen = re.search(r"<genInfo>.*?</genInfo>", xml_text, re.S)
    if not gen:
        raise UniverseReconstructionError(f"{accession}: no <genInfo> block in N-PORT XML")
    rep_pd = re.search(r"<repPdDate>([^<]+)</repPdDate>", gen.group())
    if not rep_pd:
        raise UniverseReconstructionError(f"{accession}: no <repPdDate> in N-PORT XML")
    report_date = date.fromisoformat(rep_pd.group(1).strip())

    holdings: list[Holding] = []
    for block in re.findall(r"<invstOrSec>.*?</invstOrSec>", xml_text, re.S):
        name_m = re.search(r"<name>([^<]*)</name>", block)
        cusip_m = re.search(r"<cusip>([^<]*)</cusip>", block)
        isin_m = re.search(r'<isin value="([^"]*)"', block)
        bal_m = re.search(r"<balance>([^<]*)</balance>", block)
        val_m = re.search(r"<valUSD>([^<]*)</valUSD>", block)
        pct_m = re.search(r"<pctVal>([^<]*)</pctVal>", block)
        asset_cat_m = re.search(r"<assetCat>([^<]*)</assetCat>", block)
        # Equity common stock is the relevant asset class for "who is in the
        # sector universe"; skip cash/repo/derivative sleeve entries so they
        # don't get mistaken for company constituents.
        if asset_cat_m and asset_cat_m.group(1).strip() not in ("EC", "EP"):
            continue
        if not name_m:
            continue
        raw_name = html.unescape(name_m.group(1)).strip()
        # A handful of older N-PORT filings put a CUSIP-style security
        # description ("XEROX HOLDINGS CORP COMMON STOCK USD1.0") in <name>
        # instead of a clean company name -- strip the trailing security-type
        # boilerplate so it resolves the same as every other row.
        raw_name = re.sub(
            r"\s+COMMON\s+STOCK(\s+USD[\d.]+)?\s*$", "", raw_name, flags=re.I
        )
        holdings.append(
            Holding(
                report_date=report_date,
                source_form=source_form,
                accession=accession,
                raw_name=raw_name,
                cusip=(cusip_m.group(1).strip() if cusip_m else None),
                isin=(isin_m.group(1).strip() if isin_m else None),
                shares_or_balance=(float(bal_m.group(1)) if bal_m else None),
                value_usd=(float(val_m.group(1)) if val_m else None),
                pct_of_fund=(float(pct_m.group(1)) if pct_m else None),
                pct_basis="disclosed",
            )
        )
    return holdings


def fetch_nport_holdings(filing: FilingRef) -> list[Holding]:
    docs = _index_documents(filing.index_url, filing.accession)
    xml_docs = [d for d in docs if d.endswith(".xml") and "xslForm" not in d]
    if not xml_docs:
        raise UniverseReconstructionError(f"{filing.accession}: no primary_doc.xml found")
    url = "https://www.sec.gov" + xml_docs[0] if xml_docs[0].startswith("/") else xml_docs[0]
    xml_text = _cached_get_text(url, filing.accession, "xml")
    return _parse_nport_xml(xml_text, source_form=filing.form_type, accession=filing.accession)


# ── N-Q / N-CSR / N-CSRS parsing (legacy joint narrative HTML) ───────────────

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_DATE_RE = re.compile(
    r"(" + "|".join(m.capitalize() for m in _MONTHS) + r")\s+(\d{1,2}),\s+(\d{4})"
)
_SECTION_HEADER_RE = re.compile(r"^[A-Z0-9&,.\'\s]+—\s*[\d.]+%\s*$")
_ROW_RE = re.compile(
    r"([A-Za-z][A-Za-z0-9&,.'\-/() ]{2,80}?)\s*\|\s*([\d,]+(?:\.\d+)?)\s*\|\s*\$?\s*([\d,]+(?:\.\d+)?)"
)


def _flatten_html(chunk: str) -> str:
    # html.unescape handles every named/numeric entity in one pass (&nbsp;,
    # &#160;, &#8212; em-dash, etc.) -- filings across the 10-year window mix
    # both named and numeric forms for the same non-breaking space.
    text = html.unescape(chunk)
    text = text.replace("\xa0", " ")
    text = _HTML_TAG_RE.sub(" | ", text)
    # Source documents wrap long cell text across a raw newline mid-name
    # (e.g. "Juniper Networks,\nInc.") with no tag in between -- collapse ALL
    # whitespace (not just spaces/tabs) to a single space so a name's
    # regex match isn't broken by an embedded line break.
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"(\s*\|\s*){2,}", " | ", text)
    return text


_ANY_FUND_NAME_RE = re.compile(r"[A-Za-z][A-Za-z &]{2,60}?\s+Select\s+Sector\s+SPDR\s+Fund", re.I)


def _find_fund_section(html_text: str, *, window: int = 220_000) -> str | None:
    """Slice out the Technology fund's own section from a jointly-filed doc.

    All 10-11 Select Sector SPDR funds are listed sequentially in one combined
    N-Q/N-CSR/N-CSRS document -- Communication Services, Consumer
    Discretionary, ..., Technology, Utilities. We anchor on the Technology
    mention immediately followed by a "SCHEDULE OF INVESTMENTS" header (there
    are usually several incidental mentions -- e.g. a table of contents entry
    -- that are not the holdings table itself), then cut the section off at
    the *next occurrence of any* "<Sector> Select Sector SPDR Fund" name
    (whichever sector comes next in the document -- NOT specifically the next
    "Technology" mention, which could be many sections later and would
    otherwise swallow several unrelated funds' holdings into this one).
    """
    tech_mentions = [m.start() for m in re.finditer(re.escape(LEGACY_FUND_NAME), html_text, re.I)]
    section_start = None
    for idx in tech_mentions:
        lookahead = html_text[idx : idx + 400]
        if re.search(r"schedule\s+of\s+investments", lookahead, re.I):
            section_start = idx
            break
    if section_start is None:
        return None
    # Multi-page tables repeat "Technology Select Sector SPDR Fund" as a
    # running header on each continuation page -- that's not a section
    # boundary, so only a mention of a genuinely *different* sector's fund
    # name ends the slice.
    any_fund_mentions = [
        m for m in _ANY_FUND_NAME_RE.finditer(html_text) if "technology" not in m.group().lower()
    ]
    next_fund = None
    for m in any_fund_mentions:
        if m.start() > section_start + 1000:
            next_fund = m.start()
            break
    section_end = next_fund if next_fund is not None else section_start + window
    section_end = min(section_end, section_start + window)
    return html_text[section_start:section_end]


def _extract_report_date(section_text: str) -> date | None:
    header = html.unescape(section_text[:2000]).replace("\xa0", " ")
    m = _DATE_RE.search(header)
    if not m:
        return None
    month = _MONTHS.index(m.group(1).lower()) + 1
    return date(int(m.group(3)), month, int(m.group(2)))


def _parse_legacy_holdings(section_text: str, *, source_form: str, accession: str) -> list[Holding]:
    report_date = _extract_report_date(section_text)
    if report_date is None:
        raise UniverseReconstructionError(f"{accession}: could not find a report date in fund section")
    flat = _flatten_html(section_text)
    rows: list[tuple[str, float, float]] = []
    for m in _ROW_RE.finditer(flat):
        raw_name, shares_s, value_s = m.groups()
        raw_name = raw_name.strip(" |")
        if _SECTION_HEADER_RE.match(raw_name.upper()):
            continue
        if len(re.sub(r"[^A-Za-z]", "", raw_name)) < 3:
            continue
        if raw_name.upper().startswith(("TOTAL", "SCHEDULE", "SECURITY DESCRIPTION")):
            continue
        # Securities-lending cash-collateral sleeves aren't sector constituents.
        if re.search(
            r"securities lending|money market (portfolio|fund)|navigator", raw_name, re.I
        ):
            continue
        if _normalize_key(raw_name) in _GENERIC_SUFFIX_NOISE:
            continue
        try:
            shares = float(shares_s.replace(",", ""))
            value = float(value_s.replace(",", ""))
        except ValueError:
            continue
        rows.append((raw_name, shares, value))
    if not rows:
        return []
    total_value = sum(v for _, _, v in rows)
    holdings: list[Holding] = []
    for raw_name, shares, value in rows:
        holdings.append(
            Holding(
                report_date=report_date,
                source_form=source_form,
                accession=accession,
                raw_name=raw_name,
                cusip=None,
                isin=None,
                shares_or_balance=shares,
                value_usd=value,
                pct_of_fund=(100.0 * value / total_value if total_value else None),
                pct_basis="computed",
            )
        )
    return holdings


def fetch_legacy_holdings(filing: FilingRef) -> list[Holding]:
    docs = _index_documents(filing.index_url, filing.accession)
    html_docs = [
        d
        for d in docs
        if d.lower().endswith((".htm", ".html"))
        and "index" not in d.lower()
        and "cert" not in d.lower()
        and "ex99" not in d.lower()
    ]
    if not html_docs:
        raise UniverseReconstructionError(f"{filing.accession}: no candidate primary document found")
    # The primary narrative document (containing every fund's SOI) is reliably
    # the largest non-exhibit .htm file in the filing.
    best_text = ""
    for doc in html_docs:
        url = "https://www.sec.gov" + doc if doc.startswith("/") else doc
        try:
            text = _cached_get_text(url, filing.accession + "_" + Path(doc).stem, "htm")
        except UniverseReconstructionError:
            continue
        if len(text) > len(best_text):
            best_text = text
    if not best_text:
        raise UniverseReconstructionError(f"{filing.accession}: could not fetch any document body")
    section = _find_fund_section(best_text)
    if section is None:
        raise UniverseReconstructionError(
            f"{filing.accession}: '{LEGACY_FUND_NAME}' schedule-of-investments section not found"
        )
    return _parse_legacy_holdings(section, source_form=filing.form_type, accession=filing.accession)


# ── Name -> ticker resolution ─────────────────────────────────────────────────

# Curated during Phase 0 by inspecting the actual names EDGAR returned across
# the 2016-2026 window (see membership_by_filing_date.csv for the full raw
# name list). This is a data-cleaning step, not a selection step -- every name
# the filings return is mapped or explicitly flagged UNRESOLVED; none are
# dropped silently. Historical/renamed/acquired entities are mapped to the
# ticker they traded under *at the time*, so a later corporate action doesn't
# erase their historical presence in the fund.
KNOWN_NAME_TO_TICKER: dict[str, str] = {
    "apple inc": "AAPL",
    "microsoft corp": "MSFT",
    "nvidia corp": "NVDA",
    "broadcom inc": "AVGO",
    "broadcom ltd": "AVGO",
    "salesforce inc": "CRM",
    "salesforce.com inc": "CRM",
    "adobe inc": "ADBE",
    "cisco systems inc": "CSCO",
    "accenture plc class a": "ACN",
    "oracle corp": "ORCL",
    "intel corp": "INTC",
    "ibm corp": "IBM",
    "international business machines corp": "IBM",
    "qualcomm inc": "QCOM",
    "texas instruments inc": "TXN",
    "amd": "AMD",
    "advanced micro devices inc": "AMD",
    "applied materials inc": "AMAT",
    "servicenow inc": "NOW",
    "intuit inc": "INTU",
    "automatic data processing inc": "ADP",
    "analog devices inc": "ADI",
    "micron technology inc": "MU",
    "lam research corp": "LRCX",
    "klac-tencor corp": "KLAC",
    "klа-tencor corp": "KLAC",
    "klc-tencor corp": "KLAC",
    "kla corp": "KLAC",
    "kla-tencor corp": "KLAC",
    "synopsys inc": "SNPS",
    "cadence design systems inc": "CDNS",
    "palo alto networks inc": "PANW",
    "fortinet inc": "FTNT",
    "crowdstrike holdings inc": "CRWD",
    "motorola solutions inc": "MSI",
    "juniper networks inc": "JNPR",
    "f5 networks inc": "FFIV",
    "f5 inc": "FFIV",
    "harris corp": "HRS",
    "corning inc": "GLW",
    "te connectivity ltd": "TEL",
    "amphenol corp class a": "APH",
    "flir systems inc": "FLIR",
    "visa inc class a": "V",
    "mastercard inc class a": "MA",
    "paypal holdings inc": "PYPL",
    "fiserv inc": "FI",
    "fidelity national information services inc": "FIS",
    "global payments inc": "GPN",
    "western union co": "WU",
    "paychex inc": "PAYX",
    "total system services inc": "TSS",
    "cognizant technology solutions corp class a": "CTSH",
    "alliance data systems corp": "ADS",
    "csra inc": "CSRA",
    "teradata corp": "TDC",
    "xerox corp": "XRX",
    "akamai technologies inc": "AKAM",
    "at&t inc": "T",
    "centurylink inc": "CTL",
    "lumen technologies inc": "LUMN",
    "frontier communications corp": "FTR",
    "level 3 communications inc": "LVLT",
    "verizon communications inc": "VZ",
    "alphabet inc class a": "GOOGL",
    "alphabet inc class c": "GOOG",
    "ebay inc": "EBAY",
    "facebook inc class a": "META",
    "meta platforms inc class a": "META",
    "verisign inc": "VRSN",
    "yahoo!, inc": "YHOO",
    "yahoo! inc": "YHOO",
    "first solar inc": "FSLR",
    "microchip technology inc": "MCHP",
    "linear technology corp": "LLTC",
    "qorvo inc": "QRVO",
    "skyworks solutions inc": "SWKS",
    "nortek inc": "NTK",
    "hewlett packard enterprise co": "HPE",
    "hp inc": "HPQ",
    "dxc technology co": "DXC",
    "gartner inc": "IT",
    "jabil inc": "JBL",
    "keysight technologies inc": "KEYS",
    "trimble inc": "TRMB",
    "arista networks inc": "ANET",
    "workday inc class a": "WDAY",
    "autodesk inc": "ADSK",
    "vmware inc class a": "VMW",
    "activision blizzard inc": "ATVI",
    "electronic arts inc": "EA",
    "take-two interactive software inc": "TTWO",
    "netapp inc": "NTAP",
    "seagate technology holdings plc": "STX",
    "western digital corp": "WDC",
    "citrix systems inc": "CTXS",
    "check point software technologies ltd": "CHKP",
    "akamai technologies, inc": "AKAM",
    "roper technologies inc": "ROP",
    "ptc inc": "PTC",
    "monolithic power systems inc": "MPWR",
    "on semiconductor corp": "ON",
    "nxp semiconductors nv": "NXPI",
    "gen digital inc": "GEN",
    "symantec corp": "SYMC",
    "mckesson corp": "MCK",
    "leidos holdings inc": "LDOS",
    "cdw corp": "CDW",
    "booz allen hamilton holding corp": "BAH",
    "manhattan associates inc": "MANH",
    "amdocs ltd": "DOX",
    "fair isaac corp": "FICO",
    "global industries ltd": "GLBL",
    "juniper networks, inc.": "JNPR",
    "solar winds corp": "SWI",
    "solarwinds corp": "SWI",
    "zebra technologies corp class a": "ZBRA",
    "netease inc": "NTES",
    "cboe global markets inc": "CBOE",
    "diebold nixdorf inc": "DBD",
    "netscout systems inc": "NTCT",
    "verint systems inc": "VRNT",
    "conduent inc": "CNDT",
    "cerner corp": "CERN",
    "shutterstock inc": "SSTK",
    "cars.com inc": "CARS",
    "cvent holding corp": "CVT",
    "expedia group inc": "EXPE",
    "j2 global inc": "JCOM",
    "sabre corp": "SABR",
    "twitter inc": "TWTR",
    "match group inc": "MTCH",
    # Names EDGAR returns without a "Class A"/"Inc"-normalized match to the
    # entries above, found while running the reconstruction across the full
    # 2016-2026 window (kept alongside the originals rather than replacing
    # them, since filings are inconsistent about "Inc" vs "Inc." vs "PLC"
    # vs "Corp/DE" over a decade of history).
    "ansys inc": "ANSS",
    "accenture plc": "ACN",
    "amphenol corp": "APH",
    "applovin corp": "APP",
    "cdw corp/de": "CDW",
    "ciena corp": "CIEN",
    "cognizant technology solutions corp": "CTSH",
    "coherent corp": "COHR",
    "datadog inc": "DDOG",
    "dell technologies inc": "DELL",
    "epam systems inc": "EPAM",
    "enphase energy inc": "ENPH",
    "godaddy inc": "GDDY",
    "lumentum holdings inc": "LITE",
    "palantir technologies inc": "PLTR",
    "qnity electronics inc": "QNTY",
    "sandisk corp/de": "SNDK",
    "super micro computer inc": "SMCI",
    "te connectivity plc": "TEL",
    "teledyne technologies inc": "TDY",
    "teradyne inc": "TER",
    "tyler technologies inc": "TYL",
    "workday inc": "WDAY",
    "zebra technologies corp": "ZBRA",
    # Pre-acquisition / pre-rename legacy tickers (the company as it actually
    # traded at that point in time -- e.g. Avago Technologies acquired
    # Broadcom Corp in 2016 and took its name, so both tickers appear
    # depending on the filing date).
    "adobe systems inc": "ADBE",
    "avago technologies ltd": "AVGO",
    "broadcom corp class a": "BRCM",
    "ca inc": "CA",
    "emc corp": "EMC",
    "red hat inc": "RHT",
    "sandisk corp": "SNDK",
    "seagate technology plc": "STX",
    "xilinx inc": "XLNX",
    "ipg photonics corp": "IPGP",
    "broadridge financial solutions inc": "BR",
    "fleetcor technologies inc": "FLT",
    "corpay inc": "CPAY",
    "cognizant technology solutions": "CTSH",
    "jack henry associates inc": "JKHY",
    "jack henry & associates inc": "JKHY",
    "mastercard inc": "MA",
    "maxim integrated products inc": "MXIM",
    "visa inc": "V",
    "western union co/the": "WU",
    "xerox holdings corp": "XRX",
    "ceridian hcm holding inc": "CDAY",
    "cisco systems inc/delaware": "CSCO",
    "nortonlifelock inc": "NLOK",
    "paycom software inc": "PAYC",
    "solaredge technologies inc": "SEDG",
    "vontier corp": "VNT",
    # "Take-Two Interactive Software, Inc." occasionally has a <br/>-style
    # tag between "Take-Two" and "Interactive..." in the raw HTML (a literal
    # tag, not just a wrapped text node), which the pipe-delimited row parser
    # -- by design -- can't rejoin across; map the truncated remainder
    # directly rather than complicate the parser for one rare row/decade.
    "interactive software inc": "TTWO",
}

# Bare corporate-suffix tokens that occasionally survive as a standalone
# regex match at a page break / table-restart boundary in the legacy
# HTML parser -- not a real holding, just parser noise from a malformed
# row split across a page. Filtered by exact (normalized) match, never by
# substring, so a real company whose name happens to contain one of these
# words is unaffected.
_GENERIC_SUFFIX_NOISE = {"corp", "inc", "inc a", "ltd", "plc", "co", "shares", "portfolio"}


def _normalize_key(name: str) -> str:
    """Normalize a company name for dict lookup.

    Legacy (N-Q/N-CSR) names carry punctuation ("Cisco Systems, Inc.") that
    N-PORT's ``<name>`` tag doesn't ("Adobe Inc") -- strip commas/periods and
    trailing footnote markers (e.g. "(a)") from both sides before matching so
    the two eras' naming conventions land on the same key.
    """
    key = name.strip().lower()
    key = key.replace(",", " ").replace(".", " ")
    # Strip one or more trailing footnote markers, e.g. "... (a) (b)".
    key = re.sub(r"(\s*\([a-z]\)\s*)+$", "", key)
    return re.sub(r"\s+", " ", key).strip()


_NORMALIZED_NAME_TO_TICKER = {_normalize_key(k): v for k, v in KNOWN_NAME_TO_TICKER.items()}


def resolve_ticker(raw_name: str) -> str:
    key = _normalize_key(raw_name)
    if key in _NORMALIZED_NAME_TO_TICKER:
        return _NORMALIZED_NAME_TO_TICKER[key]
    # Try stripping a trailing "Class A/B/C" suffix as a second pass.
    stripped = re.sub(r"\s+class\s+[a-c]$", "", key)
    if stripped in _NORMALIZED_NAME_TO_TICKER:
        return _NORMALIZED_NAME_TO_TICKER[stripped]
    return f"UNRESOLVED:{raw_name.strip()}"


# ── Orchestration ─────────────────────────────────────────────────────────────


def holdings_to_frame(all_holdings: list[Holding]) -> pd.DataFrame:
    rows = []
    for h in all_holdings:
        rows.append(
            {
                "report_date": h.report_date.isoformat(),
                "source_form": h.source_form,
                "accession": h.accession,
                "raw_name": h.raw_name,
                "ticker": resolve_ticker(h.raw_name),
                "cusip": h.cusip,
                "isin": h.isin,
                "shares_or_balance": h.shares_or_balance,
                "value_usd": h.value_usd,
                "pct_of_fund": h.pct_of_fund,
                "pct_basis": h.pct_basis,
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["rank_in_filing"] = (
        df.groupby("report_date")["pct_of_fund"].rank(ascending=False, method="first")
    )
    return df.sort_values(["report_date", "rank_in_filing"]).reset_index(drop=True)


def reconstruct_universe(
    *,
    start_year: int = 2016,
    end_year: int | None = None,
    use_cache: bool = True,
    include_ncsr_fallback: bool = True,
    verbose: bool = True,
) -> tuple[pd.DataFrame, list[dict]]:
    """Fetch + parse every relevant filing, return (membership_df, run_log).

    ``run_log`` records one entry per filing attempted, including any that
    failed to parse -- so parsing gaps are visible in the output rather than
    silently absorbed.
    """
    filings = list_series_filings(["NPORT-P", "N-Q"])
    if include_ncsr_fallback:
        # N-PORT-P gives clean, complete quarterly coverage from 2019 on, so
        # N-CSR/N-CSRS is only useful as a gap-filler in the pre-2019 window
        # N-Q doesn't fully cover -- restricting the fetch here avoids ~15
        # wasted requests/parses per run for filings whose periods are
        # already covered.
        filings += [f for f in list_series_filings(["N-CSR", "N-CSRS"]) if int(f.filing_date[:4]) <= 2019]
    filings.sort(key=lambda r: r.filing_date)

    end_year = end_year or (date.today().year + 1)
    filings = [f for f in filings if start_year <= int(f.filing_date[:4]) <= end_year]

    # N-Q / N-CSR / N-CSRS jointly cover the pre-2019 window; once N-PORT-P
    # starts (2019+), prefer it and only use N-CSR/N-CSRS as a gap-filler for
    # any quarter N-Q/N-PORT-P didn't produce holdings for.
    nport = [f for f in filings if f.form_type == "NPORT-P"]
    nq = [f for f in filings if f.form_type == "N-Q"]
    ncsr = [f for f in filings if f.form_type in ("N-CSR", "N-CSRS")]

    all_holdings: list[Holding] = []
    run_log: list[dict] = []
    covered_dates: set[str] = set()

    def _run(refs: list[FilingRef], fetcher, label: str) -> None:
        for f in refs:
            try:
                holdings = fetcher(f)
                if not holdings:
                    run_log.append(
                        {"accession": f.accession, "form": f.form_type, "filing_date": f.filing_date,
                         "status": "empty", "n_holdings": 0}
                    )
                    if verbose:
                        print(f"  [{label}] {f.filing_date} {f.accession}: 0 holdings parsed (skipped)")
                    continue
                report_date = holdings[0].report_date.isoformat()
                covered_dates.add(report_date)
                all_holdings.extend(holdings)
                run_log.append(
                    {"accession": f.accession, "form": f.form_type, "filing_date": f.filing_date,
                     "status": "ok", "report_date": report_date, "n_holdings": len(holdings)}
                )
                if verbose:
                    print(f"  [{label}] {f.filing_date} {f.accession}: {len(holdings)} holdings as of {report_date}")
            except UniverseReconstructionError as exc:
                run_log.append(
                    {"accession": f.accession, "form": f.form_type, "filing_date": f.filing_date,
                     "status": "error", "error": str(exc)}
                )
                if verbose:
                    print(f"  [{label}] {f.filing_date} {f.accession}: FAILED -- {exc}")

    if verbose:
        print(f"Fetching {len(nport)} N-PORT-P filings...")
    _run(nport, fetch_nport_holdings, "NPORT-P")

    if verbose:
        print(f"Fetching {len(nq)} N-Q filings...")
    _run(nq, fetch_legacy_holdings, "N-Q")

    if verbose:
        print(f"Fetching {len(ncsr)} N-CSR/N-CSRS filings (fallback pass)...")
    for f in ncsr:
        # Only use N-CSR/N-CSRS if we don't already have holdings for a report
        # date extremely close to it (fallback semantics: fill gaps, don't
        # duplicate a period N-Q already covered).
        try:
            holdings = fetch_legacy_holdings(f)
        except UniverseReconstructionError as exc:
            run_log.append(
                {"accession": f.accession, "form": f.form_type, "filing_date": f.filing_date,
                 "status": "error", "error": str(exc)}
            )
            if verbose:
                print(f"  [N-CSR/N-CSRS] {f.filing_date} {f.accession}: FAILED -- {exc}")
            continue
        if not holdings:
            run_log.append(
                {"accession": f.accession, "form": f.form_type, "filing_date": f.filing_date,
                 "status": "empty", "n_holdings": 0}
            )
            continue
        report_date = holdings[0].report_date.isoformat()
        if report_date in covered_dates:
            run_log.append(
                {"accession": f.accession, "form": f.form_type, "filing_date": f.filing_date,
                 "status": "skipped_duplicate_period", "report_date": report_date}
            )
            if verbose:
                print(f"  [N-CSR/N-CSRS] {f.filing_date} {f.accession}: period {report_date} already covered, skipped")
            continue
        covered_dates.add(report_date)
        all_holdings.extend(holdings)
        run_log.append(
            {"accession": f.accession, "form": f.form_type, "filing_date": f.filing_date,
             "status": "ok", "report_date": report_date, "n_holdings": len(holdings)}
        )
        if verbose:
            print(f"  [N-CSR/N-CSRS] {f.filing_date} {f.accession}: {len(holdings)} holdings as of {report_date} (gap-fill)")

    return holdings_to_frame(all_holdings), run_log


def screen_candidates(
    membership_df: pd.DataFrame,
    *,
    exclude_tickers: Iterable[str] = (),
    target_n: int = 16,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rank tickers by continuity + materiality; return (candidates, historical_only).

    ``candidates`` is the screened net-new list (excludes ``exclude_tickers``
    and anything still UNRESOLVED). ``historical_only`` lists every ticker
    that was a constituent at some point but has dropped out of the fund by
    the most recent filing -- retained for transparency (per the build plan)
    even though there's no forward path to onboard a delisted/acquired name.
    """
    if membership_df.empty:
        return pd.DataFrame(), pd.DataFrame()
    resolved = membership_df[~membership_df["ticker"].str.startswith("UNRESOLVED:")].copy()
    exclude = {t.upper() for t in exclude_tickers}
    n_periods_total = resolved["report_date"].nunique()
    latest_date = resolved["report_date"].max()

    grouped = (
        resolved.groupby("ticker")
        .agg(
            first_seen=("report_date", "min"),
            last_seen=("report_date", "max"),
            n_periods_present=("report_date", "nunique"),
            mean_pct_of_fund=("pct_of_fund", "mean"),
            mean_rank=("rank_in_filing", "mean"),
        )
        .reset_index()
    )
    grouped["presence_ratio"] = grouped["n_periods_present"] / n_periods_total
    grouped["still_constituent"] = grouped["last_seen"] == latest_date

    historical_only = grouped[~grouped["still_constituent"]].sort_values(
        ["last_seen", "mean_pct_of_fund"], ascending=[False, False]
    )

    pool = grouped[grouped["still_constituent"] & ~grouped["ticker"].isin(exclude)].copy()
    pool = pool.sort_values(["presence_ratio", "mean_pct_of_fund"], ascending=[False, False])
    candidates = pool.head(target_n).reset_index(drop=True)
    return candidates, historical_only.reset_index(drop=True)


def write_outputs(
    membership_df: pd.DataFrame,
    candidates: pd.DataFrame,
    historical_only: pd.DataFrame,
    run_log: list[dict],
) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    membership_df.to_csv(OUT_DIR / "membership_by_filing_date.csv", index=False)
    candidates.to_csv(OUT_DIR / "candidate_list.csv", index=False)
    candidates.to_json(OUT_DIR / "candidate_list.json", orient="records", indent=2)
    historical_only.to_csv(OUT_DIR / "historical_only_constituents.csv", index=False)
    with open(OUT_DIR / "run_log.json", "w", encoding="utf-8") as fh:
        json.dump(run_log, fh, indent=2)
    unresolved = sorted(
        set(membership_df.loc[membership_df["ticker"].str.startswith("UNRESOLVED:"), "raw_name"])
    )
    with open(OUT_DIR / "unresolved_names.json", "w", encoding="utf-8") as fh:
        json.dump(unresolved, fh, indent=2)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start-year", type=int, default=2016)
    ap.add_argument("--end-year", type=int, default=None)
    ap.add_argument("--target-n", type=int, default=16)
    ap.add_argument(
        "--exclude-tickers",
        nargs="+",
        default=["AAPL", "MSFT", "NVDA", "AMZN"],
        help="Tickers already in the pilot -- excluded from the *net-new* candidate list "
        "(they still appear in membership_by_filing_date.csv if XLK actually holds them).",
    )
    ap.add_argument("--no-ncsr-fallback", action="store_true", help="Skip N-CSR/N-CSRS gap-filling.")
    ap.add_argument("--no-cache", action="store_true", help="Refetch every filing, ignoring the raw_filings/ cache.")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    membership_df, run_log = reconstruct_universe(
        start_year=args.start_year,
        end_year=args.end_year,
        use_cache=not args.no_cache,
        include_ncsr_fallback=not args.no_ncsr_fallback,
        verbose=not args.quiet,
    )
    if membership_df.empty:
        print("No holdings parsed -- nothing to write.", file=sys.stderr)
        return 1

    candidates, historical_only = screen_candidates(
        membership_df, exclude_tickers=args.exclude_tickers, target_n=args.target_n
    )
    write_outputs(membership_df, candidates, historical_only, run_log)

    n_ok = sum(1 for r in run_log if r["status"] == "ok")
    n_err = sum(1 for r in run_log if r["status"] == "error")
    n_periods = membership_df["report_date"].nunique()
    print()
    print(f"Parsed {n_ok}/{len(run_log)} filings successfully ({n_err} failed) "
          f"covering {n_periods} distinct point-in-time snapshots "
          f"{membership_df['report_date'].min()} .. {membership_df['report_date'].max()}.")
    print(f"Candidate net-new list ({len(candidates)} tickers) -> {OUT_DIR / 'candidate_list.csv'}")
    print(f"Full membership table -> {OUT_DIR / 'membership_by_filing_date.csv'}")
    unresolved_n = membership_df["ticker"].str.startswith("UNRESOLVED:").sum()
    if unresolved_n:
        print(f"WARNING: {unresolved_n} holding rows have an unresolved name->ticker mapping "
              f"-- see {OUT_DIR / 'unresolved_names.json'}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
