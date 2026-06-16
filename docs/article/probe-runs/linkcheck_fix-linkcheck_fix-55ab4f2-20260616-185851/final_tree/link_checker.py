#!/usr/bin/env python3
"""Точка входа: поиск и проверка ссылок в .md файлах.

Также служит пакетом — реэкспортирует cli, http_client, link_parser
как атрибуты, чтобы работало `from link_checker import cli`.
"""

import sys

# Импортируем плоские модули из той же директории
import cli  # noqa: F401
import http_client  # noqa: F401
import link_parser  # noqa: F401

if __name__ == "__main__":
    sys.exit(cli.run())
