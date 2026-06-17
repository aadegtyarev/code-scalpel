"""Web search via DuckDuckGo Lite.

Returns a short list of result titles + snippets so the agent can look
up syntax, conventions, or error messages without relying on hardcoded
examples in prompts.

The agent can save useful findings to `.code-scalpel/knowledge.md`
via `write_file` — those persist across tasks as a project-local
knowledge base.
"""

from __future__ import annotations

import html
import re

import httpx

from code_scalpel.untrusted import wrap_untrusted

_USER_AGENT = "code-scalpel/agent (+https://github.com/aadegtyarev/code-scalpel)"
_TIMEOUT = 15.0
_MAX_RESULTS = 6
_SNIPPET_CAP = 300


async def search_top_url(query: str) -> tuple[str, str] | None:
    """Return (title, url) of the top DDG result, or None if no results.

    Used by `web_learn` to find the most relevant page to fetch.
    """
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            resp = await client.post(
                "https://lite.duckduckgo.com/lite/",
                data={"q": query, "kl": "wt-wt"},
            )
    except httpx.HTTPError as e:
        raise RuntimeError(f"web_search network error: {e}") from e

    if resp.status_code >= 400:
        raise RuntimeError(f"web_search: HTTP {resp.status_code}")

    return _top_result(resp.text)


def _top_result(html_text: str) -> tuple[str, str] | None:
    """Return (title, url) of the first result, or None."""
    link_re = re.compile(
        r"""<a\b[^>]+class=['""]result-link['""][^>]*href=['""]([^'"">]+)['""][^>]*>(.*?)</a>"""
        r"""|<a\b[^>]+href=['""]([^'"">]+)['""][^>]*class=['""]result-link['""][^>]*>(.*?)</a>""",
        re.DOTALL,
    )

    def clean(s: str) -> str:
        s = re.sub(r"<[^>]+>", "", s)
        return html.unescape(" ".join(s.split()))

    for m in link_re.finditer(html_text):
        url = m.group(1) or m.group(3) or ""
        title = clean(m.group(2) or m.group(4) or "")
        if url and title:
            return title, url
    return None


async def web_search(query: str, max_results: int = _MAX_RESULTS) -> str:
    """Search DuckDuckGo Lite and return formatted result titles + snippets.

    Raises `RuntimeError` on network failure so the caller can surface
    it as a tool error rather than silently returning empty results.
    """
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            resp = await client.post(
                "https://lite.duckduckgo.com/lite/",
                data={"q": query, "kl": "wt-wt"},
            )
    except httpx.HTTPError as e:
        raise RuntimeError(f"web_search network error: {e}") from e

    if resp.status_code >= 400:
        raise RuntimeError(f"web_search: HTTP {resp.status_code}")

    # Search results are external content (threat-model T08/T15) — a
    # result snippet can carry an injection payload. Wrap the formatted
    # result so the model treats it as data, not instructions.
    return wrap_untrusted(
        _parse_ddg_lite(resp.text, max_results=max_results), source=f"web-search:{query}"
    )


def _parse_ddg_lite(html_text: str, max_results: int = _MAX_RESULTS) -> str:
    """Extract result titles, URLs and snippets from DDG Lite HTML.

    DDG Lite uses single-quoted attributes:
      <a href="..." class='result-link'>Title</a>
      <td class='result-snippet'>snippet</td>
    """
    # DDG Lite uses either quote style; handle both.
    link_re = re.compile(
        r"""<a\b[^>]+class=['""]result-link['""][^>]*href=['""]([^'"">]+)['""][^>]*>(.*?)</a>"""
        r"""|<a\b[^>]+href=['""]([^'"">]+)['""][^>]*class=['""]result-link['""][^>]*>(.*?)</a>""",
        re.DOTALL,
    )
    snippet_re = re.compile(
        r"""<td\b[^>]+class=['""]result-snippet['""][^>]*>(.*?)</td>""",
        re.DOTALL,
    )

    snippets_raw = snippet_re.findall(html_text)

    def clean(s: str) -> str:
        s = re.sub(r"<[^>]+>", "", s)
        s = html.unescape(s)
        return " ".join(s.split())

    results: list[str] = []
    for m in link_re.finditer(html_text):
        if len(results) >= max_results:
            break
        # Two alternations: (url1, title1, url2, title2)
        url = m.group(1) or m.group(3) or ""
        title_raw = m.group(2) or m.group(4) or ""
        t = clean(title_raw)
        if not t or not url:
            continue
        i = len(results)
        snippet = clean(snippets_raw[i]) if i < len(snippets_raw) else ""
        if len(snippet) > _SNIPPET_CAP:
            snippet = snippet[:_SNIPPET_CAP] + "…"
        results.append(f"{i + 1}. **{t}**\n   {url}\n   {snippet}")

    if not results:
        return "No results found."
    return "\n\n".join(results)
