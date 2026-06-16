"""Парсинг ссылок из Markdown-файлов и HTML."""

import html.parser
import os
import re
import urllib.parse


# Регулярные выражения для разных типов Markdown-ссылок

# [text](url) — inline-ссылки и изображения
RE_INLINE = re.compile(
    r'!?\[([^\]]*)\]\(([^)]+)\)'
)

# <url> — автоссылки
RE_AUTOLINK = re.compile(
    r'<([a-zA-Z][a-zA-Z0-9+.-]*://[^>]+)>'
)

# [ref]: url — reference-style (определения ссылок)
RE_REF_DEF = re.compile(
    r'^\[([^\]]+)\]:\s+(\S+)',
    re.MULTILINE,
)

# [text][ref] — использование reference-style ссылок
RE_REF_USE = re.compile(r'\[([^\]]*)\]\[([^\]]*)\]')


class _LinkExtractor(html.parser.HTMLParser):
    """HTML-парсер, собирающий ссылки из тегов <a href> и <img src>."""

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "a":
            href = attrs_dict.get("href")
            if href:
                absolute = urllib.parse.urljoin(self.base_url, href)
                self.links.append(absolute)
        elif tag == "img":
            src = attrs_dict.get("src")
            if src:
                absolute = urllib.parse.urljoin(self.base_url, src)
                self.links.append(absolute)


def extract_links(html: str, base_url: str) -> list[str]:
    """Извлечь все ссылки из HTML-кода.

    Парсит теги <a href> и <img src>, разрешая относительные URL
    относительно base_url.
    """
    parser = _LinkExtractor(base_url)
    parser.feed(html)
    return parser.links


def is_valid_url(url: str) -> bool:
    """Проверить, является ли строка валидным URL."""
    if not url or not url.strip():
        return False
    parsed = urllib.parse.urlparse(url)
    return bool(parsed.scheme) or bool(parsed.netloc) or bool(parsed.path)


def find_md_files(root_dir: str = ".") -> list[str]:
    """Рекурсивно найти все .md файлы, исключая .venv и скрытые директории."""
    md_files = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith('.') and d != '__pycache__']
        for filename in filenames:
            if filename.endswith('.md'):
                md_files.append(os.path.join(dirpath, filename))
    return sorted(md_files)


def extract_links_from_text(text: str, filepath: str) -> list[dict]:
    """Извлечь все ссылки из Markdown-текста.

    Возвращает список словарей: {'url': str, 'line': int, 'type': str}.
    """
    links = []

    ref_defs = {}
    for match in RE_REF_DEF.finditer(text):
        ref_name = match.group(1).strip().lower()
        ref_url = match.group(2).strip()
        line_num = text[:match.start()].count('\n') + 1
        ref_defs[ref_name] = {'url': ref_url, 'line': line_num}

    for match in RE_INLINE.finditer(text):
        raw_url = match.group(2).strip()
        line_num = text[:match.start()].count('\n') + 1
        if raw_url and not raw_url.startswith('#'):
            links.append({
                'url': raw_url,
                'line': line_num,
                'type': 'inline',
            })

    for match in RE_AUTOLINK.finditer(text):
        url = match.group(1).strip()
        line_num = text[:match.start()].count('\n') + 1
        links.append({'url': url, 'line': line_num, 'type': 'autolink'})

    for match in RE_REF_USE.finditer(text):
        ref_name = match.group(2).strip().lower()
        line_num = text[:match.start()].count('\n') + 1
        if ref_name in ref_defs:
            links.append({
                'url': ref_defs[ref_name]['url'],
                'line': line_num,
                'type': 'reference',
            })

    return links


def extract_links_from_file(filepath: str) -> list[dict]:
    """Извлечь ссылки из одного .md файла."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as e:
        print(f"Ошибка чтения {filepath}: {e}")
        return []

    return extract_links_from_text(text, filepath)


def is_http_url(url: str) -> bool:
    """Проверить, является ли URL HTTP/HTTPS ссылкой."""
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme in ('http', 'https')


def is_relative_url(url: str) -> bool:
    """Проверить, является ли URL относительным."""
    parsed = urllib.parse.urlparse(url)
    return not parsed.scheme and not parsed.netloc and bool(url)
