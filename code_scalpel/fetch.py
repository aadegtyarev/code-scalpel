"""Fetch a URL and convert its HTML body to markdown.

Used by `/learn <name> --url <url>` so the model gets a clean,
structured representation of the doc page rather than raw HTML
(too noisy) or plain text (loses headings, code blocks, lists —
exactly the structure that makes a recipe coherent).

`html2text` was picked over BeautifulSoup-based alternatives
because (a) it produces markdown directly, no extra step, (b) it's
small and pure-Python — fits the project's "small, local,
composable" принцип, (c) we'd rather pass some sidebar/nav noise
to the model (it can ignore it) than pull in a heavyweight content
extractor like trafilatura.
"""

from __future__ import annotations

import html2text
import httpx

# Cap the converted markdown to keep one recipe from blowing the
# whole model context. A typical doc page is 5–30 KB of markdown
# after conversion; sites with infinite-scroll docs can go higher.
# 40 KB is a soft ceiling — enough for a real reference page, well
# under the 16k–32k token budget once tokenized.
_MAX_MARKDOWN_CHARS = 40_000

# Block downloads bigger than this BEFORE conversion. PDFs, .tar.gz,
# binary blobs accidentally linked as docs — we don't want to spend
# memory or CPU on them.
_MAX_FETCH_BYTES = 2_000_000  # 2 MB

# Be polite + give the server something to log. Bare httpx UA looks
# like a scraping bot; this identifies us honestly.
_USER_AGENT = "code-scalpel/learn (+https://github.com/aadegtyarev/code-scalpel)"

# Request timeout — 15s is generous for a doc fetch and snappy
# enough that a hung server doesn't freeze /learn.
_TIMEOUT_SECONDS = 15.0


def _html_to_markdown(html: str) -> str:
    """Convert HTML body to markdown with sensible defaults.

    `body_width=0` disables word-wrap (we don't want hard-wrapped
    text — the model handles flow on its own). Images are dropped
    because the binary can't render them and the alt-text noise
    crowds out actual content.
    """
    h = html2text.HTML2Text()
    h.body_width = 0
    h.ignore_images = True
    h.ignore_emphasis = False
    h.skip_internal_links = True
    return h.handle(html).strip()


async def fetch_markdown(url: str) -> str:
    """Fetch `url` and return its body as markdown.

    Raises `RuntimeError` (with a short, user-readable message) on
    HTTP errors, oversize bodies, or non-HTML content types so the
    `/learn --url` path can surface the failure inline instead of
    silently feeding garbage to the model.
    """
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            resp = await client.get(url)
    except httpx.HTTPError as e:
        raise RuntimeError(f"fetch failed: {e}") from e

    if resp.status_code >= 400:
        raise RuntimeError(f"fetch returned HTTP {resp.status_code}")

    content_type = resp.headers.get("content-type", "").lower()
    if content_type and not (
        "html" in content_type or "xml" in content_type or "text/plain" in content_type
    ):
        raise RuntimeError(f"fetch returned non-HTML content-type: {content_type}")

    if len(resp.content) > _MAX_FETCH_BYTES:
        raise RuntimeError(
            f"fetch body too large: {len(resp.content)} bytes (cap {_MAX_FETCH_BYTES})"
        )

    md = _html_to_markdown(resp.text)
    if len(md) > _MAX_MARKDOWN_CHARS:
        # Truncate with an explicit marker so the model knows context
        # was cut — better than silently feeding a half-page.
        md = md[:_MAX_MARKDOWN_CHARS] + f"\n\n…[truncated to {_MAX_MARKDOWN_CHARS} chars]"
    return md
