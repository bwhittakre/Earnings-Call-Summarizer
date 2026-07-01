from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    cleaned = text.strip()
    if "\ufffd" in cleaned:
        logger.warning(
            "Transcript contains replacement characters (U+FFFD); check source file encoding."
        )
    return cleaned
