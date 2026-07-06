from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from src.ingest.dates import resolve_as_of_date_value
from src.ingest.filings.analysis_corpus import build_analysis_corpus
from src.ingest.filings.corpus import build_tagged_corpus, load_document, load_eight_k_documents, section_tag
from src.ingest.filings.excerpt_puller import DEFAULT_MAX_ANALYSIS_CHARS, pull_excerpts
from src.ingest.filings.fiscal import (
    fiscal_year_prefix,
    is_q4_quarter,
    normalize_quarter_label,
    parse_quarters_list,
    prior_quarter_labels_for_fy_q4,
)
from src.ingest.filings.manifest import load_manifest, validate_manifest
from src.ingest.filings.types import (
    DEFAULT_EXCERPT_MODE,
    DocumentType,
    ExcerptMode,
    FilingLoadError,
    FilingPackage,
    LoadedDocument,
)
from src.paths import EXCERPT_AUDIT_DIR


@dataclass(frozen=True)
class ExcerptConfig:
    mode: ExcerptMode = DEFAULT_EXCERPT_MODE
    max_analysis_chars: int = DEFAULT_MAX_ANALYSIS_CHARS
    write_audit: bool = False


def normalize_excerpt_mode(mode: str) -> ExcerptMode:
    normalized = mode.strip().lower()
    if normalized in {"smart", "full", "off"}:
        return "full" if normalized == "off" else normalized  # type: ignore[return-value]
    raise FilingLoadError(
        f"Invalid excerpt mode {mode!r}; expected smart, full, or off."
    )


def _document_key(doc: LoadedDocument) -> str:
    if doc.doc_type == DocumentType.EIGHT_K:
        label = doc.section_label or doc.path.stem
        return f"8-K:{label}"
    return f"{doc.doc_type.value}:{doc.quarter_label or ''}"


def _parse_companies(companies: str) -> list[str]:
    tickers = [item.strip().upper() for item in companies.split(",") if item.strip()]
    if not tickers:
        raise FilingLoadError("--companies must list at least one ticker.")
    return tickers


def _resolve_quarter_folder(ticker_root: Path, quarter: str) -> Path:
    normalized = normalize_quarter_label(quarter)
    direct = ticker_root / normalized
    if direct.is_dir():
        return direct

    matches = sorted(
        (
            path
            for path in ticker_root.rglob(normalized)
            if path.is_dir() and path.name == normalized
        ),
        key=lambda path: len(path.parts),
    )
    if not matches:
        raise FilingLoadError(
            f"Quarter folder not found for {ticker_root.name}: {normalized} "
            f"(expected {direct} or nested .../{normalized}/)"
        )
    if len(matches) > 1:
        paths = ", ".join(str(path.relative_to(ticker_root)) for path in matches)
        raise FilingLoadError(
            f"Multiple quarter folders found for {ticker_root.name} {normalized}: {paths}"
        )
    return matches[0]


def _quarter_folder(ticker_root: Path, quarter: str) -> Path:
    return _resolve_quarter_folder(ticker_root, quarter)


def _append_event_documents(
    folder: Path,
    documents: list[LoadedDocument],
    warnings: list[str],
) -> None:
    documents.extend(load_eight_k_documents(folder))

    for doc_type in (
        DocumentType.PRESS_RELEASE,
        DocumentType.INVESTOR_PRESENTATION,
    ):
        loaded = load_document(folder, doc_type)
        if loaded:
            documents.append(loaded)
        else:
            warnings.append(f"Missing {doc_type.name.lower()} in {folder.name}.")


def _load_q1_q3_documents(folder: Path, quarter: str) -> tuple[list[LoadedDocument], list[str]]:
    warnings: list[str] = []
    documents: list[LoadedDocument] = []

    ten_q = load_document(folder, DocumentType.TEN_Q, quarter_label=quarter)
    if ten_q:
        documents.append(ten_q)

    _append_event_documents(folder, documents, warnings)

    material = ten_q or any(
        doc.doc_type in {DocumentType.EIGHT_K, DocumentType.PRESS_RELEASE}
        for doc in documents
    )
    if not material:
        raise FilingLoadError(
            f"Q1–Q3 folder must include at least one of 10-Q, 8-K, or press_release: {folder}"
        )

    if ten_q is None:
        warnings.append(f"Missing 10-Q in {folder.name}.")
    if not any(doc.doc_type == DocumentType.EIGHT_K for doc in documents):
        warnings.append(f"Missing eight_k in {folder.name}.")

    return documents, warnings


def _load_q4_documents(
    folder: Path,
    quarter: str,
    ticker_root: Path,
    fiscal_year: str,
) -> tuple[list[LoadedDocument], list[str]]:
    warnings: list[str] = []
    documents: list[LoadedDocument] = []

    ten_k = load_document(folder, DocumentType.TEN_K, quarter_label=quarter)
    if ten_k is None:
        raise FilingLoadError(f"Q4 folder requires 10-K: {folder}")
    documents.append(ten_k)

    for prior_label in prior_quarter_labels_for_fy_q4(fiscal_year):
        try:
            prior_folder = _resolve_quarter_folder(ticker_root, prior_label)
        except FilingLoadError:
            warnings.append(f"Missing sibling quarter folder for Q4 context: {prior_label}")
            continue
        prior_ten_q = load_document(
            prior_folder,
            DocumentType.TEN_Q,
            quarter_label=prior_label,
        )
        if prior_ten_q is None:
            warnings.append(f"Missing 10-Q in sibling folder {prior_label}.")
            continue
        documents.append(prior_ten_q)

    _append_event_documents(folder, documents, warnings)
    if not any(doc.doc_type == DocumentType.EIGHT_K for doc in documents):
        warnings.append(f"Missing eight_k in {folder.name}.")

    return documents, warnings


def _build_corpora(
    documents: list[LoadedDocument],
    *,
    quarter: str,
    excerpt_config: ExcerptConfig,
) -> tuple[str, str, dict]:
    raw_corpus_text = build_tagged_corpus(documents)
    if excerpt_config.mode == "full":
        stats = {
            "raw_corpus_chars": len(raw_corpus_text),
            "analysis_corpus_chars": len(raw_corpus_text),
            "excerpt_count": len(documents),
            "per_document": [
                {
                    "doc_key": _document_key(doc),
                    "raw_chars": len(doc.text),
                    "excerpt_chars": len(doc.text),
                    "excerpt_count": 1,
                }
                for doc in documents
            ],
        }
        return raw_corpus_text, raw_corpus_text, stats

    pull_result = pull_excerpts(
        documents,
        primary_quarter=quarter,
        max_analysis_chars=excerpt_config.max_analysis_chars,
    )
    analysis_corpus_text, stats_obj = build_analysis_corpus(documents, pull_result.documents)
    return raw_corpus_text, analysis_corpus_text, stats_obj.to_dict()


def write_excerpt_audit(label: str, analysis_corpus_text: str) -> Path:
    EXCERPT_AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    path = EXCERPT_AUDIT_DIR / f"{label}.txt"
    path.write_text(analysis_corpus_text, encoding="utf-8")
    return path


def build_filing_package(
    *,
    ticker: str,
    quarter: str,
    folder: Path,
    ticker_root: Path,
    require_as_of_date: bool = False,
    excerpt_config: ExcerptConfig | None = None,
) -> FilingPackage:
    config = excerpt_config or ExcerptConfig()
    ticker_key = ticker.strip().upper()
    normalized_quarter = normalize_quarter_label(quarter)
    manifest = load_manifest(folder)
    company_name, as_of_date_text, manifest_fiscal_year, manifest_warnings = validate_manifest(
        manifest,
        folder=folder,
        ticker=ticker_key,
        quarter=normalized_quarter,
        require_as_of_date=require_as_of_date,
    )
    warnings = list(manifest_warnings)
    fiscal_year = manifest_fiscal_year or fiscal_year_prefix(normalized_quarter)
    q4 = is_q4_quarter(normalized_quarter)

    if q4:
        documents, load_warnings = _load_q4_documents(
            folder,
            normalized_quarter,
            ticker_root,
            fiscal_year,
        )
    else:
        documents, load_warnings = _load_q1_q3_documents(folder, normalized_quarter)

    warnings.extend(load_warnings)
    raw_corpus_text, analysis_corpus_text, excerpt_stats = _build_corpora(
        documents,
        quarter=normalized_quarter,
        excerpt_config=config,
    )
    if not analysis_corpus_text.strip():
        raise FilingLoadError(f"No document text loaded for {ticker_key} {normalized_quarter}")

    as_of_date = resolve_as_of_date_value(
        as_of_date_text,
        required=require_as_of_date,
    )

    doc_map = {_document_key(doc): doc for doc in documents}

    package = FilingPackage(
        ticker=ticker_key,
        quarter=normalized_quarter,
        folder=folder,
        company_name=company_name,
        fiscal_year=fiscal_year,
        as_of_date=as_of_date,
        as_of_date_text=as_of_date_text,
        documents=doc_map,
        raw_corpus_text=raw_corpus_text,
        analysis_corpus_text=analysis_corpus_text,
        corpus_text=analysis_corpus_text,
        excerpt_stats=excerpt_stats,
        is_q4=q4,
        warnings=warnings,
    )
    if config.write_audit:
        write_excerpt_audit(package.audit_label(), analysis_corpus_text)
    return package


def load_filing_packages(
    filings_root: Path,
    *,
    companies: str,
    quarter: str,
    require_as_of_date: bool = False,
    excerpt_config: ExcerptConfig | None = None,
) -> list[FilingPackage]:
    if not filings_root.is_dir():
        raise FilingLoadError(f"Filings root not found: {filings_root}")

    normalized_quarter = normalize_quarter_label(quarter)
    packages: list[FilingPackage] = []
    for ticker in _parse_companies(companies):
        ticker_root = filings_root / ticker
        if not ticker_root.is_dir():
            raise FilingLoadError(f"Ticker folder not found: {ticker_root}")
        folder = _quarter_folder(ticker_root, normalized_quarter)
        packages.append(
            build_filing_package(
                ticker=ticker,
                quarter=normalized_quarter,
                folder=folder,
                ticker_root=ticker_root,
                require_as_of_date=require_as_of_date,
                excerpt_config=excerpt_config,
            )
        )
    return sorted(packages, key=lambda pkg: pkg.ticker)


def load_filing_packages_by_company_quarters(
    filings_root: Path,
    *,
    company_quarters: dict[str, str],
    require_as_of_date: bool = False,
    excerpt_config: ExcerptConfig | None = None,
) -> list[FilingPackage]:
    if not filings_root.is_dir():
        raise FilingLoadError(f"Filings root not found: {filings_root}")

    packages: list[FilingPackage] = []
    for ticker, quarter in sorted(company_quarters.items()):
        ticker_key = ticker.strip().upper()
        normalized_quarter = normalize_quarter_label(quarter)
        ticker_root = filings_root / ticker_key
        if not ticker_root.is_dir():
            raise FilingLoadError(f"Ticker folder not found: {ticker_root}")
        folder = _quarter_folder(ticker_root, normalized_quarter)
        packages.append(
            build_filing_package(
                ticker=ticker_key,
                quarter=normalized_quarter,
                folder=folder,
                ticker_root=ticker_root,
                require_as_of_date=require_as_of_date,
                excerpt_config=excerpt_config,
            )
        )
    return sorted(packages, key=lambda pkg: pkg.ticker)


def dry_run_report(
    filings_root: Path,
    *,
    companies: str,
    quarter: str,
    require_as_of_date: bool = False,
    excerpt_config: ExcerptConfig | None = None,
) -> str:
    quarters = parse_quarters_list(quarter)
    lines = [
        f"Filings root: {filings_root}",
        f"Companies: {companies}",
        f"Quarters: {', '.join(quarters)}",
    ]
    config = excerpt_config or ExcerptConfig()
    lines.append(f"Excerpt mode: {config.mode}")

    all_packages = []
    for normalized_quarter in quarters:
        try:
            packages = load_filing_packages(
                filings_root,
                companies=companies,
                quarter=normalized_quarter,
                require_as_of_date=require_as_of_date,
                excerpt_config=config,
            )
        except FilingLoadError as exc:
            lines.append(f"Validation: FAILED for {normalized_quarter} - {exc}")
            return "\n".join(lines)
        all_packages.extend(packages)

    lines.append(f"Packages: {len(all_packages)}")
    for package in all_packages:
        lines.append(
            f"  - {package.ticker} {package.quarter} "
            f"({'Q4/10-K' if package.is_q4 else 'Q1–Q3'}) "
            f"path={package.folder} "
            f"docs={len(package.documents)} "
            f"raw_corpus_chars={len(package.raw_corpus_text)} "
            f"analysis_corpus_chars={len(package.analysis_corpus_text)} "
            f"excerpt_count={package.excerpt_stats.get('excerpt_count', 0)}"
        )
        if package.company_name:
            lines.append(f"      company: {package.company_name}")
        if package.as_of_date_text:
            lines.append(f"      as_of_date: {package.as_of_date_text}")
        eight_k_docs = [
            doc for doc in package.documents.values() if doc.doc_type == DocumentType.EIGHT_K
        ]
        if eight_k_docs:
            lines.append(f"      8-K files: {len(eight_k_docs)}")
            for doc in eight_k_docs:
                tag = section_tag(doc.doc_type, section_label=doc.section_label)
                lines.append(f"        - {doc.path.name} -> === {tag} ===")
        for warning in package.warnings:
            lines.append(f"      warning: {warning}")
    lines.append("Validation: OK")
    return "\n".join(lines)


def dry_run_report_for_quarter_end(
    filings_root: Path,
    *,
    company_quarters: dict[str, str],
    anchor_date: date,
    require_as_of_date: bool = False,
    excerpt_config: ExcerptConfig | None = None,
) -> str:
    from src.ingest.dates import format_as_of_date

    lines = [
        f"Filings root: {filings_root}",
        f"Quarter-end anchor: {anchor_date.isoformat()}",
    ]
    for ticker, quarter in sorted(company_quarters.items()):
        lines.append(f"  {ticker}: {quarter}")
    config = excerpt_config or ExcerptConfig()
    lines.append(f"Excerpt mode: {config.mode}")

    try:
        packages = load_filing_packages_by_company_quarters(
            filings_root,
            company_quarters=company_quarters,
            require_as_of_date=require_as_of_date,
            excerpt_config=config,
        )
    except FilingLoadError as exc:
        lines.append(f"Validation: FAILED - {exc}")
        return "\n".join(lines)

    lines.append(f"Packages: {len(packages)}")
    for package in packages:
        lines.append(
            f"  - {package.ticker} {package.quarter} "
            f"({'Q4/10-K' if package.is_q4 else 'Q1–Q3'}) "
            f"path={package.folder} "
            f"docs={len(package.documents)} "
            f"raw_corpus_chars={len(package.raw_corpus_text)} "
            f"analysis_corpus_chars={len(package.analysis_corpus_text)} "
            f"excerpt_count={package.excerpt_stats.get('excerpt_count', 0)}"
        )
        if package.company_name:
            lines.append(f"      company: {package.company_name}")
        lines.append(f"      anchor_as_of_date: {format_as_of_date(anchor_date)}")
        if package.as_of_date_text:
            lines.append(f"      manifest_as_of_date: {package.as_of_date_text}")
        for warning in package.warnings:
            lines.append(f"      warning: {warning}")
    lines.append("Validation: OK")
    return "\n".join(lines)
