"""Prebuilt PDF reader tool for ezagent.

Reads text from a PDF — either fetched from a URL or read from a local file path.
Supports page ranges to keep extracted text within context limits.

Dependencies: pypdf, requests
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Optional

import pypdf
import requests
from fastmcp import FastMCP

mcp = FastMCP("pdf_reader")

MAX_CHARS = 100_000
DOWNLOAD_TIMEOUT = 30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_text(
    reader: pypdf.PdfReader,
    start_page: int,
    end_page: Optional[int],
    max_chars: int,
) -> tuple[str, int, bool]:
    """Extract text from pages [start_page, end_page] (both 1-indexed, inclusive).

    Returns (text, total_pages, truncated).
    """
    total = len(reader.pages)
    # Convert to 0-indexed, clamp to valid range
    first = max(0, start_page - 1)
    last = min(total, end_page if end_page is not None else total)

    parts = []
    for i in range(first, last):
        page_text = reader.pages[i].extract_text() or ""
        parts.append(f"--- Page {i + 1} ---\n{page_text}")

    text = "\n\n".join(parts)
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars] + "\n\n[Content truncated]"

    return text, total, truncated


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def pdf_read(
    source: str,
    max_chars: int = 50_000,
    start_page: int = 1,
    end_page: Optional[int] = None,
) -> str:
    """Read and extract text from a PDF file.

    Accepts either a URL or a local file path as the source. Use start_page /
    end_page to read only a subset of pages and stay within context limits.

    Args:
        source: URL to a PDF (e.g. "https://arxiv.org/pdf/1706.03762.pdf") or an
                absolute/relative local file path.
        max_chars: Maximum characters to return (default 50,000; hard cap 100,000).
        start_page: First page to read, 1-indexed (default 1).
        end_page: Last page to read, inclusive and 1-indexed (default: all pages).
    """
    try:
        max_chars = max(1, min(max_chars, MAX_CHARS))

        if source.startswith("http://") or source.startswith("https://"):
            headers = {"User-Agent": "Mozilla/5.0 (compatible; ezagent/1.0)"}
            resp = requests.get(source, headers=headers, timeout=DOWNLOAD_TIMEOUT)
            resp.raise_for_status()
            reader = pypdf.PdfReader(io.BytesIO(resp.content))
        else:
            p = Path(source).expanduser().resolve()
            if not p.is_file():
                return json.dumps({"error": f"File not found: {p}"})
            reader = pypdf.PdfReader(str(p))

        text, total_pages, truncated = _extract_text(reader, start_page, end_page, max_chars)
        actual_end = end_page if end_page is not None else total_pages

        return json.dumps(
            {
                "source": source,
                "total_pages": total_pages,
                "pages_read": f"{start_page}-{min(actual_end, total_pages)}",
                "truncated": truncated,
                "char_count": len(text),
                "text": text,
            }
        )
    except Exception as e:
        return json.dumps({"error": str(e), "source": source})


if __name__ == "__main__":
    mcp.run()
