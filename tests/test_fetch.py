"""fetch_markdown — HTML→markdown converter for `/learn --url`.

Tests don't make real HTTP calls — they install a custom httpx
transport that returns the body we hand-built. This pins both the
happy path and every guard rail (HTTP error, oversize body,
non-HTML content-type) without flake from a network round-trip.
"""

from __future__ import annotations

import httpx
import pytest

from code_scalpel import fetch as fetch_mod
from code_scalpel.fetch import fetch_markdown

_HTML_SAMPLE = """\
<html><body>
<h1>Redis Basics</h1>
<p>An <em>in-memory</em> data store.</p>
<ul><li>SET key value</li><li>GET key</li></ul>
<pre><code>redis-cli ping</code></pre>
</body></html>
"""


def _make_transport(
    *, status_code: int = 200, headers: dict[str, str] | None = None, body: bytes = b""
) -> httpx.MockTransport:
    """Build an httpx MockTransport that returns the given fixed response."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, headers=headers or {}, content=body)

    return httpx.MockTransport(handler)


# Captured BEFORE any test monkey-patches `fetch_mod.httpx.AsyncClient`,
# so the lambda below doesn't recurse into its own replacement.
_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _inject_transport(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport) -> None:
    """Route `code_scalpel.fetch`'s AsyncClient calls through `transport`."""
    monkeypatch.setattr(
        fetch_mod.httpx,
        "AsyncClient",
        lambda **kw: _REAL_ASYNC_CLIENT(**{**kw, "transport": transport}),
    )


@pytest.mark.asyncio
async def test_fetch_markdown_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sample HTML round-trips into markdown with the structure preserved —
    h1 becomes `#`, em becomes `*…*`, list items become `*` bullets."""
    transport = _make_transport(
        status_code=200,
        headers={"content-type": "text/html; charset=utf-8"},
        body=_HTML_SAMPLE.encode(),
    )
    _inject_transport(monkeypatch, transport)

    md = await fetch_markdown("https://example.invalid/redis")

    assert "# Redis Basics" in md
    # html2text uses underscores for emphasis (CommonMark-compatible).
    assert "_in-memory_" in md
    assert "SET key value" in md
    assert "redis-cli ping" in md
    # HTML tags themselves don't survive.
    assert "<h1>" not in md
    assert "<pre>" not in md


@pytest.mark.asyncio
async def test_fetch_markdown_raises_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """4xx/5xx must surface as a clean RuntimeError — `/learn --url` can
    then print the message inline rather than silently feeding noise to
    the model."""
    transport = _make_transport(
        status_code=404, headers={"content-type": "text/html"}, body=b"<h1>nope</h1>"
    )
    _inject_transport(monkeypatch, transport)

    with pytest.raises(RuntimeError, match="HTTP 404"):
        await fetch_markdown("https://example.invalid/missing")


@pytest.mark.asyncio
async def test_fetch_markdown_rejects_non_html_content_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A PDF or octet-stream linked as a doc — refuse early, don't try
    to "convert" binary garbage."""
    transport = _make_transport(
        status_code=200,
        headers={"content-type": "application/pdf"},
        body=b"%PDF-1.4\n...",
    )
    _inject_transport(monkeypatch, transport)

    with pytest.raises(RuntimeError, match="non-HTML"):
        await fetch_markdown("https://example.invalid/spec.pdf")


@pytest.mark.asyncio
async def test_fetch_markdown_truncates_oversize_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    """A doc page with infinite scroll gets capped so one recipe doesn't
    blow the whole model context. The cap leaves an explicit marker so
    the model sees the cut."""
    huge_html = "<html><body><p>" + ("blah " * 20_000) + "</p></body></html>"
    transport = _make_transport(
        status_code=200,
        headers={"content-type": "text/html"},
        body=huge_html.encode(),
    )
    _inject_transport(monkeypatch, transport)

    md = await fetch_markdown("https://example.invalid/huge")
    assert len(md) <= 40_000 + 100  # cap + marker overhead
    assert "truncated" in md
