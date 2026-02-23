"""Prebuilt Arxiv tool for ezagent.

Provides structured paper search and retrieval via the public Arxiv Atom API.
No API key required.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from typing import Optional

import requests
from fastmcp import FastMCP

mcp = FastMCP("arxiv")

ARXIV_API_URL = "http://export.arxiv.org/api/query"

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}

_VALID_SORT_BY = {"relevance", "lastUpdatedDate", "submittedDate"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_id(raw: str) -> str:
    """Strip URL prefix and version suffix from an arxiv ID."""
    pid = raw.strip()
    if "/abs/" in pid:
        pid = pid.split("/abs/")[-1]
    elif pid.startswith("arxiv:"):
        pid = pid[6:]
    return re.sub(r"v\d+$", "", pid)


def _parse_entry(entry: ET.Element) -> dict:
    """Parse a single Atom <entry> element into a plain dict."""

    def text(tag: str) -> str:
        el = entry.find(tag, _NS)
        return el.text.strip() if el is not None and el.text else ""

    raw_id = text("atom:id")
    paper_id = _normalize_id(raw_id)

    authors = [
        el.find("atom:name", _NS).text.strip()
        for el in entry.findall("atom:author", _NS)
        if el.find("atom:name", _NS) is not None
    ]

    categories = [c.get("term", "") for c in entry.findall("atom:category", _NS)]

    # Prefer the explicit PDF link; fall back to constructed URL
    pdf_url = ""
    for link in entry.findall("atom:link", _NS):
        if link.get("type") == "application/pdf":
            pdf_url = link.get("href", "")
            break
    if not pdf_url and paper_id:
        pdf_url = f"https://arxiv.org/pdf/{paper_id}.pdf"

    return {
        "id": paper_id,
        "title": re.sub(r"\s+", " ", text("atom:title")),
        "authors": authors,
        "abstract": re.sub(r"\s+", " ", text("atom:summary")),
        "published": text("atom:published"),
        "updated": text("atom:updated"),
        "categories": categories,
        "pdf_url": pdf_url,
        "abs_url": f"https://arxiv.org/abs/{paper_id}",
    }


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def arxiv_search(
    query: str,
    max_results: int = 10,
    sort_by: str = "relevance",
    category: Optional[str] = None,
) -> str:
    """Search Arxiv for papers matching a query.

    Args:
        query: Free-text search query (e.g. "vision transformers" or "diffusion models image generation").
        max_results: Number of papers to return (default 10, max 50).
        sort_by: Sort order — "relevance", "lastUpdatedDate", or "submittedDate".
        category: Optional Arxiv category filter (e.g. "cs.LG", "cs.CV", "stat.ML", "cs.CL").
    """
    try:
        max_results = max(1, min(max_results, 50))
        if sort_by not in _VALID_SORT_BY:
            sort_by = "relevance"

        search_query = f"({query}) AND cat:{category}" if category else query

        params = {
            "search_query": search_query,
            "start": 0,
            "max_results": max_results,
            "sortBy": sort_by,
            "sortOrder": "descending",
        }
        resp = requests.get(ARXIV_API_URL, params=params, timeout=20)
        resp.raise_for_status()

        root = ET.fromstring(resp.text)
        total_el = root.find("opensearch:totalResults", _NS)
        total = int(total_el.text) if total_el is not None and total_el.text else 0
        papers = [_parse_entry(e) for e in root.findall("atom:entry", _NS)]

        return json.dumps({"total_results": total, "returned": len(papers), "papers": papers})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def arxiv_get(paper_id: str) -> str:
    """Fetch full metadata for a specific Arxiv paper by its ID.

    Args:
        paper_id: The Arxiv paper ID (e.g. "1706.03762", "2303.08774") or a full
                  arxiv.org URL (e.g. "https://arxiv.org/abs/1706.03762").
    """
    try:
        pid = _normalize_id(paper_id)
        resp = requests.get(ARXIV_API_URL, params={"id_list": pid}, timeout=20)
        resp.raise_for_status()

        root = ET.fromstring(resp.text)
        entries = root.findall("atom:entry", _NS)
        if not entries:
            return json.dumps({"error": f"No paper found with ID: {pid}"})

        return json.dumps({"paper": _parse_entry(entries[0])})
    except Exception as e:
        return json.dumps({"error": str(e)})


if __name__ == "__main__":
    mcp.run()
