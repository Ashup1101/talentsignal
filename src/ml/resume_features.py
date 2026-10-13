"""Resume PDF → salary-model inputs, in memory only (Phase 5.4; called by the Phase 6 app).

Resumes are personal data: the PDF and its text are never written to disk, S3
or logs. Text-based PDFs only (no OCR): a scanned or image-only PDF has no text,
which raises NoTextError with a message the app can show as is.

Skills come from the same dictionary as the postings (src/skills/dictionary.py),
and features from the same build_features() the salary model was trained with
(src/ml/features.py), so a resume and a posting are described identically.
"""

from __future__ import annotations

import io
from collections.abc import Iterable

import pandas as pd
import pdfplumber
from pdfminer.pdfparser import PDFSyntaxError
from pdfplumber.utils.exceptions import PdfminerException

from src.ml import features
from src.ml.features import FeatureSpec, Profile
from src.skills.dictionary import find_skills

__all__ = ["MAX_PAGES", "NoTextError", "build_features", "extract_text", "find_skills"]

MAX_PAGES = 10  # resumes are 1–3 pages; caps the work a huge upload can cause


class NoTextError(ValueError):
    """The PDF has no extractable text (e.g. a scanned resume)."""


def extract_text(pdf_bytes: bytes) -> str:
    """Extract a PDF's text without touching the disk.

    Args:
        pdf_bytes: The uploaded file's bytes.

    Returns:
        The text of the first MAX_PAGES pages, pages separated by newlines.

    Raises:
        ValueError: If the bytes aren't a readable PDF.
        NoTextError: If the PDF has no text (scanned or image-only).
    """
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages[:MAX_PAGES]]
    except (PDFSyntaxError, PdfminerException) as exc:
        raise ValueError("This file isn't a readable PDF.") from exc
    text = "\n".join(pages).strip()
    if not text:
        raise NoTextError(
            "No text found in this PDF. Scanned or image-only resumes aren't supported: "
            "upload a text-based PDF (for example, exported from Word or Google Docs)."
        )
    return text


def build_features(
    skills: Iterable[str], role: str, seniority: str, state: str | None, remote: bool, spec: FeatureSpec
) -> pd.DataFrame:
    """Describe a resume + the user's choices exactly as training described postings.

    Args:
        skills: Skills found on the resume (find_skills).
        role: Target role the user picked.
        seniority: Seniority the user picked (D5: chosen, not inferred).
        state: Two-letter state the user picked, or None.
        remote: Whether the user wants remote work.
        spec: The trained model's feature spec (from the exported feature_spec.json).

    Returns:
        A one-row feature table for the salary model.

    Raises:
        ValueError: If the role isn't one the model knows.
    """
    return features.build_features([Profile(role, seniority, state, remote, frozenset(skills))], spec)
