#!/usr/bin/env python3
"""Скрипт для поиска и проверки ссылок в .md файлах."""

import argparse
import os
import re
import sys
import urllib.parse

import requests


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

# Таймаут HTTP-запроса в секундах
HTTP_TIMEOUT = 10

# Сессия с переиспользованием соединений
_HTTP_SESSION: requests.Session | None = None


def _get_session() -> requests.Session:
    global _HTTP_SESSION
    if _HTTP_SESSION is None:
        _HTTP_SESSION = requests.Session()
        _HTTP_SESSION.headers.update({
            "User-Agent": "link-checker/0.1",
        })
    return _HTTP_SESSION


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

    # Собираем определения reference-style ссылок
    ref_defs = {}
    for match in RE_REF_DEF.finditer(text):
        ref_name = match.group(1).strip().lower()
        ref_url = match.group(2).strip()
        line_num = text[:match.start()].count('\n') + 1
        ref_defs[ref_name] = {'url': ref_url, 'line': line_num}

    # Ищем inline-ссылки [text](url)
    for match in RE_INLINE.finditer(text):
        raw_url = match.group(2).strip()
        line_num = text[:match.start()].count('\n') + 1
        if raw_url and not raw_url.startswith('#'):
            links.append({
                'url': raw_url,
                'line': line_num,
                'type': 'inline',
            })

    # Ищем автоссылки <url>
    for match in RE_AUTOLINK.finditer(text):
        url = match.group(1).strip()
        line_num = text[:match.start()].count('\n') + 1
        links.append({'url': url, 'line': line_num, 'type': 'autolink'})

    # Ищем использования reference-style ссылок [text][ref]
    RE_REF_USE = re.compile(r'\[([^\]]*)\]\[([^\]]*)\]')
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
        print(f"Ошибка чтения {filepath}: {e}", file=sys.stderr)
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


def check_http_url(url: str) -> dict:
    """Проверить HTTP/HTTPS ссылку.

    Возвращает {'ok': bool, 'status': str}.
    Сначала HEAD, при неудаче — GET.
    """
    session = _get_session()

    # Извлекаем URL без якоря для запроса
    parsed = urllib.parse.urlparse(url)
    clean_url = urllib.parse.urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path,
         parsed.params, parsed.query, '')
    )
    if not clean_url:
        clean_url = url

    try:
        # HEAD-запрос
        resp = session.head(clean_url, timeout=HTTP_TIMEOUT, allow_redirects=True)

        # Некоторые серверы не отвечают на HEAD или возвращают 405
        if resp.status_code in (405, 501):
            resp = session.get(clean_url, timeout=HTTP_TIMEOUT, allow_redirects=True)

        if resp.status_code < 400:
            return {'ok': True, 'status': f'{resp.status_code} OK'}
        else:
            reason = requests.status_codes._codes.get(resp.status_code, ['Unknown'])[0]
            return {'ok': False, 'status': f'{resp.status_code} {reason}'}

    except requests.exceptions.Timeout:
        return {'ok': False, 'status': 'Timeout (таимаут)'}
    except requests.exceptions.ConnectionError:
        return {'ok': False, 'status': 'ConnectionError (нет соединения)'}
    except requests.exceptions.SSLError:
        return {'ok': False, 'status': 'SSLError (ошибка SSL)'}
    except requests.exceptions.TooManyRedirects:
        return {'ok': False, 'status': 'TooManyRedirects (слишком много редиректов)'}
    except Exception as e:
        return {'ok': False, 'status': f'{type(e).__name__}: {e}'}


def check_local_file(url: str, md_filepath: str) -> dict:
    """Проверить локальный/относительный файл."""
    md_dir = os.path.dirname(os.path.abspath(md_filepath))
    target_path = os.path.normpath(os.path.join(md_dir, url))

    if os.path.isfile(target_path):
        return {'ok': True, 'status': 'файл найден'}
    else:
        return {'ok': False, 'status': f'файл не найден: {target_path}'}


def check_link(url: str, md_filepath: str) -> dict:
    """Проверить одну ссылку.

    Возвращает {'ok': bool, 'status': str}.
    """
    if is_http_url(url):
        return check_http_url(url)
    elif is_relative_url(url):
        return check_local_file(url, md_filepath)
    else:
        # mailto:, tel:, ftp: и т.п. — пропускаем
        return {'ok': True, 'status': 'пропущено (не HTTP и не файл)'}


def cmd_extract(args: argparse.Namespace) -> None:
    """Команда --extract: вывести все ссылки из .md файлов."""
    root = args.root or "."
    md_files = find_md_files(root)

    if not md_files:
        print("Не найдено .md файлов.")
        return

    for filepath in md_files:
        links = extract_links_from_file(filepath)
        print(f"# {filepath}")
        for link in links:
            print(f"  [{link['type']}] {link['url']}")
        if links:
            print()


def cmd_check(args: argparse.Namespace) -> None:
    """Команда --check: проверить все ссылки на доступность."""
    root = args.root or "."
    md_files = find_md_files(root)

    if not md_files:
        print("Не найдено .md файлов.")
        return

    total = 0
    ok_count = 0
    broken = 0

    for filepath in md_files:
        links = extract_links_from_file(filepath)
        for link in links:
            total += 1
            result = check_link(link['url'], filepath)
            line = link['line']
            if result['ok']:
                ok_count += 1
                print(f"  ✓ {filepath}:{line}  {link['url']}  →  {result['status']}")
            else:
                broken += 1
                print(f"  ✗ {filepath}:{line}  {link['url']}  →  {result['status']}")

    print()
    print(f"Проверено: {total}, доступно: {ok_count}, битых: {broken}")

    if broken > 0:
        print("ВНИМАНИЕ: найдены битые ссылки!", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Поиск и проверка ссылок в .md файлах",
    )
    parser.add_argument(
        "--root", "-r",
        default=".",
        help="Корневая директория для поиска .md файлов (по умолчанию: .)",
    )
    parser.add_argument(
        "--extract",
        action="store_true",
        help="Извлечь и вывести все ссылки из .md файлов",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Проверить доступность всех ссылок",
    )
    args = parser.parse_args(argv)

    if args.extract:
        cmd_extract(args)
    elif args.check:
        cmd_check(args)
    else:
        parser.print_help()

    return 0


if __name__ == "__main__":
    sys.exit(main())
