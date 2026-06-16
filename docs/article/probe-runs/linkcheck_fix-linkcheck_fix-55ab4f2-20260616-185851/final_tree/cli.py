"""CLI-интерфейс для проверки ссылок в Markdown-файлах."""

import argparse
import os
import sys

from link_parser import extract_links_from_file, find_md_files, is_http_url, is_relative_url
from http_client import check_link


def cmd_extract(args: argparse.Namespace) -> None:
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


def check_local_file(url: str, md_filepath: str) -> tuple[bool, str]:
    md_dir = os.path.dirname(os.path.abspath(md_filepath))
    target_path = os.path.normpath(os.path.join(md_dir, url))
    if os.path.isfile(target_path):
        return True, "файл найден"
    else:
        return False, f"файл не найден: {target_path}"


def cmd_check(args: argparse.Namespace) -> None:
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
            url = link['url']
            line = link['line']

            if is_http_url(url):
                status_code = check_link(url, timeout=10)
                if status_code == 0:
                    broken += 1
                    print(f"  ✗ {filepath}:{line}  {url}  →  ошибка соединения")
                elif status_code < 400:
                    ok_count += 1
                    print(f"  ✓ {filepath}:{line}  {url}  →  {status_code}")
                else:
                    broken += 1
                    print(f"  ✗ {filepath}:{line}  {url}  →  {status_code}")
            elif is_relative_url(url):
                is_ok, status = check_local_file(url, filepath)
                if is_ok:
                    ok_count += 1
                else:
                    broken += 1
                status_line = "  ✓ " if is_ok else "  ✗ "
                print(f"{status_line}{filepath}:{line}  {url}  →  {status}")
            else:
                ok_count += 1
                print(f"  ✓ {filepath}:{line}  {url}  →  пропущено")

    print()
    print(f"Проверено: {total}, доступно: {ok_count}, битых: {broken}")

    if broken > 0:
        print("ВНИМАНИЕ: найдены битые ссылки!", file=sys.stderr)


def run(argv: list[str] | None = None) -> int:
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
