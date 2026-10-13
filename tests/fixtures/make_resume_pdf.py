"""Write resume_sample.pdf: a small, made-up, text-based resume for the tests.

Hand-built PDF (one page, standard Helvetica font) so the fixture is reviewable
code, not an opaque binary. Regenerate with:

    python -m tests.fixtures.make_resume_pdf
"""

from __future__ import annotations

from pathlib import Path

RESUME_PATH = Path(__file__).with_name("resume_sample.pdf")
# Made up. Expected dictionary skills: Python, SQL, Spark, Airflow, AWS, dbt, Docker, PostgreSQL.
RESUME_LINES = [
    "Alex Example",
    "Data Engineer | Austin, TX",
    "Skills: Python, SQL, Apache Spark, Airflow, AWS, dbt, Docker",
    "Experience",
    "Data Engineer, Example Corp (2021-2025): built batch pipelines in PySpark on AWS,",
    "orchestrated with Airflow; modeled analytics marts in dbt on PostgreSQL.",
    "Education: B.S. Computer Science",
]


def pdf_with_lines(lines: list[str]) -> bytes:
    """Build a one-page PDF showing each line as real (extractable) text.

    Args:
        lines: ASCII text lines; an empty list gives a page with no text at all,
            like a scanned resume without OCR.

    Returns:
        The PDF file's bytes.
    """
    def escape(line: str) -> str:
        return line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    shown = "".join(f"({escape(line)}) Tj T* " for line in lines)
    stream = f"BT /F1 11 Tf 14 TL 72 740 Td {shown}ET".encode("ascii") if lines else b""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref_at)
    return bytes(out)


if __name__ == "__main__":
    RESUME_PATH.write_bytes(pdf_with_lines(RESUME_LINES))
    print(f"Wrote {RESUME_PATH} ({RESUME_PATH.stat().st_size} bytes)")
