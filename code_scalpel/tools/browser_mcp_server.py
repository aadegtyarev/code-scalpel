#!/usr/bin/env python3
"""Browser MCP server — Playwright automation via stdio JSON-RPC."""
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server

server = Server("browser")
_page: Any = None
_browser: Any = None


async def _ensure_browser():
    global _browser
    if _browser is None:
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        _browser = await pw.chromium.launch(headless=True)


async def _ensure_page():
    global _page
    if _page is None or _page.is_closed():
        await _ensure_browser()
        ctx = await _browser.new_context()
        _page = await ctx.new_page()
    return _page


def _resolve(page, selector: str):
    s = selector.strip()
    m = re.match(r'^(button|link|textbox|heading|combobox|checkbox)\s+"(.+)"$', s)
    if m:
        return page.get_by_role(m.group(1), name=m.group(2))
    if s.startswith("#") or s.startswith("."):
        return page.locator(s)
    return page.get_by_text(s)


def _format_a11y(node: dict[str, Any], indent: int = 0) -> str:
    role = node.get("role", "?")
    name = node.get("name", "")
    value = node.get("value", "")
    prefix = "  " * indent
    line = f"{prefix}{role}"
    if name: line += f' "{name}"'
    if value: line += f" = {value}"
    lines = [line]
    for child in node.get("children", []):
        lines.append(_format_a11y(child, indent + 1))
    return "\n".join(lines)


@server.list_tools()
async def list_tools() -> list[Any]:
    from mcp.types import Tool
    return [
        Tool(name="browser_navigate", description="Open a URL. Returns page title and URL.",
             inputSchema={"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}),
        Tool(name="browser_snapshot", description="Accessibility snapshot of current page.",
             inputSchema={"type": "object", "properties": {}}),
        Tool(name="browser_click", description='Click element. Selector: \'button "Submit"\', \'#id\', \'.class\'.',
             inputSchema={"type": "object", "properties": {"selector": {"type": "string"}}, "required": ["selector"]}),
        Tool(name="browser_type", description="Type text into input field.",
             inputSchema={"type": "object", "properties": {"selector": {"type": "string"}, "text": {"type": "string"}}, "required": ["selector", "text"]}),
        Tool(name="browser_screenshot", description="Take full-page screenshot.",
             inputSchema={"type": "object", "properties": {"path": {"type": "string", "default": "screenshot.png"}}}),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[Any]:
    from mcp.types import TextContent
    page = await _ensure_page()

    if name == "browser_navigate":
        await page.goto(arguments["url"], wait_until="domcontentloaded", timeout=15000)
        title = await page.title()
        return [TextContent(type="text", text=f"{page.url}\nTitle: {title}")]

    if name == "browser_snapshot":
        # Playwright Python doesn't support accessibility snapshots directly.
        # Extract visible text and interactive elements from the DOM.
        text = await page.evaluate("""() => {
            const walk = (el, depth) => {
                if (!el || depth > 10) return '';
                const tag = el.tagName?.toLowerCase() || '';
                if (tag === 'script' || tag === 'style' || tag === 'noscript') return '';
                const role = el.getAttribute('role') || tag;
                const name = el.getAttribute('aria-label') || el.getAttribute('name') || el.getAttribute('placeholder') || '';
                const text = el.childNodes.length === 1 && el.childNodes[0].nodeType === 3
                    ? el.textContent?.trim()?.substring(0, 60) : '';
                let result = '  '.repeat(depth) + role + (name ? ' \"' + name + '\"' : '') + (text ? ': ' + text : '');
                for (const c of el.children) {
                    const child = walk(c, depth + 1);
                    if (child) result += '\\n' + child;
                }
                return result;
            };
            return walk(document.body, 0);
        }""")
        return [TextContent(type="text", text=text or "(empty page)")]

    if name == "browser_click":
        loc = _resolve(page, arguments["selector"])
        await loc.click(timeout=5000)
        return [TextContent(type="text", text=f"Clicked: {arguments['selector']}")]

    if name == "browser_type":
        loc = _resolve(page, arguments["selector"])
        await loc.fill(arguments["text"], timeout=5000)
        return [TextContent(type="text", text=f"Typed '{arguments['text']}' into {arguments['selector']}")]

    if name == "browser_screenshot":
        out = Path(arguments.get("path", "screenshot.png")).resolve()
        await page.screenshot(path=str(out), full_page=True)
        return [TextContent(type="text", text=f"Screenshot: {out}")]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
