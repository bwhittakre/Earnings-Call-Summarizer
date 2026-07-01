from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = PROJECT_ROOT / "output_confidence"

ERRORS_DIR = OUTPUT_ROOT / "errors"
EVIDENCE_AUDIT_DIR = OUTPUT_ROOT / "evidence_audit"
QUARANTINE_DIR = OUTPUT_ROOT / "quarantine"
DROPPED_EVIDENCE_DIR = OUTPUT_ROOT / "dropped_evidence"
EXCERPT_AUDIT_DIR = OUTPUT_ROOT / "excerpt_audit"
DEFAULT_SUMMARY_OUTPUT = OUTPUT_ROOT / "summary.xlsx"
