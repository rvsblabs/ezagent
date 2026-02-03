"""Prebuilt HTTP client tool for ezagent.

Provides a generic HTTP client that lets agents interact with any REST API.
No API keys required — auth is handled via headers the agent passes.
"""

from __future__ import annotations

import json
import re
from typing import Optional

import requests
from fastmcp import FastMCP

mcp = FastMCP("http")

# ---------------------------------------------------------------------------
# HTML stripping helper (same pattern as web_search)
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

MAX_BODY_CHARS = 50_000
MAX_READ_CHARS = 20_000

ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"}


def _strip_html(html: str) -> str:
    """Crude HTML-to-text: remove tags and collapse whitespace."""
    text = _TAG_RE.sub(" ", html)
    text = _WS_RE.sub(" ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def http_request(
    method: str,
    url: str,
    headers: Optional[str] = None,
    body: Optional[str] = None,
    params: Optional[str] = None,
) -> str:
    """Make an HTTP request to any URL.

    Args:
        method: HTTP method — GET, POST, PUT, PATCH, DELETE, or HEAD.
        url: The full URL to request.
        headers: Optional JSON string of HTTP headers (e.g. '{"Authorization": "Bearer xxx"}').
        body: Optional request body as a JSON string.
        params: Optional query parameters as a JSON string (e.g. '{"page": "1"}').
    """
    try:
        method_upper = method.upper()
        if method_upper not in ALLOWED_METHODS:
            return json.dumps(
                {"error": f"Unsupported method '{method}'. Allowed: {', '.join(sorted(ALLOWED_METHODS))}"}
            )

        req_headers = json.loads(headers) if headers else {}
        req_params = json.loads(params) if params else None
        req_body = body

        # If body looks like JSON, send as JSON
        req_json = None
        if req_body:
            try:
                req_json = json.loads(req_body)
                req_body = None  # use json= kwarg instead
            except (json.JSONDecodeError, TypeError):
                pass  # send as raw body string

        resp = requests.request(
            method_upper,
            url,
            headers=req_headers,
            params=req_params,
            json=req_json,
            data=req_body,
            timeout=30,
        )

        # Build response body
        resp_body: str | dict
        content_type = resp.headers.get("Content-Type", "")
        if "application/json" in content_type:
            try:
                resp_body = resp.json()
            except (json.JSONDecodeError, ValueError):
                resp_body = resp.text
        else:
            resp_body = resp.text

        # Truncate string bodies
        if isinstance(resp_body, str) and len(resp_body) > MAX_BODY_CHARS:
            resp_body = resp_body[:MAX_BODY_CHARS] + "\n\n[Content truncated]"

        return json.dumps(
            {
                "status_code": resp.status_code,
                "headers": dict(resp.headers),
                "body": resp_body,
            }
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def http_read(url: str, headers: Optional[str] = None) -> str:
    """Shorthand GET that strips HTML tags and returns plain text.

    Useful for reading web pages or HTML endpoints.
    Content is truncated to ~20,000 characters.

    Args:
        url: The URL to fetch.
        headers: Optional JSON string of HTTP headers.
    """
    try:
        req_headers = json.loads(headers) if headers else {
            "User-Agent": "Mozilla/5.0 (compatible; ezagent/1.0)",
        }

        resp = requests.get(url, headers=req_headers, timeout=30)
        resp.raise_for_status()
        text = _strip_html(resp.text)
        if len(text) > MAX_READ_CHARS:
            text = text[:MAX_READ_CHARS] + "\n\n[Content truncated]"
        return json.dumps({"url": url, "content": text})
    except Exception as e:
        return json.dumps({"error": str(e), "url": url})


if __name__ == "__main__":
    mcp.run()
