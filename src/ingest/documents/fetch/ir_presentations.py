from __future__ import annotations

import logging

from src.ingest.documents.fetch.edgar_client import EdgarClient
from src.ingest.documents.models import DocumentType, FetchedDocument, FetchRequest

logger = logging.getLogger(__name__)


def fetch_ir_presentation(
    client: EdgarClient,
    ticker: str,
    provider: str | None,
    request: FetchRequest,
) -> FetchedDocument | None:
    if not provider:
        return None
    logger.info(
        "IR presentation fetch for %s (%s) not implemented; skipping %s provider",
        request.ticker,
        request.quarter_label,
        provider,
    )
    return None
