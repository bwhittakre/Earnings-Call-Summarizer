from __future__ import annotations

import json
from pathlib import Path

from src.ingest.edgar.models import FetchResult, FetchedDocument, QuarterFetchPlan
from src.ingest.filings.sec_sanitize import sanitize_filing_text


def _package_is_complete(folder: Path, plan: QuarterFetchPlan) -> bool:
    if not (folder / "manifest.json").is_file():
        return False
    for doc in plan.documents:
        if not (folder / doc.filename).is_file():
            return False
    return True


def write_quarter_package(
    plan: QuarterFetchPlan,
    documents: list[FetchedDocument],
) -> Path:
    plan.folder.mkdir(parents=True, exist_ok=True)

    manifest_documents = []
    for doc in documents:
        path = plan.folder / doc.filename
        path.write_text(doc.text, encoding="utf-8")
        manifest_documents.append(
            {
                "doc_type": doc.doc_type,
                "accession_number": doc.filing.accession_number,
                "filing_date": doc.filing.filing_date.isoformat(),
                "report_date": (
                    doc.filing.report_date.isoformat()
                    if doc.filing.report_date
                    else None
                ),
                "source_url": doc.filing.source_url,
                "filename": doc.filename,
                "char_count": doc.char_count,
            }
        )

    manifest = {
        "ticker": plan.ticker,
        "company_name": plan.company_name,
        "quarter": plan.quarter,
        "fiscal_year": plan.fiscal_year,
        "as_of_date": plan.as_of_date_text,
        "period_end": plan.period_end.isoformat(),
        "documents": manifest_documents,
    }
    (plan.folder / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return plan.folder


def should_skip_fetch(folder: Path, plan: QuarterFetchPlan, *, overwrite: bool) -> bool:
    if overwrite:
        return False
    return _package_is_complete(folder, plan)
