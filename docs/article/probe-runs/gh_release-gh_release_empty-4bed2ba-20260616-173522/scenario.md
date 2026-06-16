# GitHub Release Publisher

CLI-утилита для автоматического создания GitHub Releases из CHANGELOG.

## Функциональность
- `gh-release publish` — читает CHANGELOG.md, находит последнюю версию, создаёт GitHub Release
- `gh-release publish --dry-run` — показывает что будет опубликовано без реального API-вызова
- `gh-release list` — показывает последние N релизов репозитория
- Аутентификация: `GITHUB_TOKEN` env var (Personal Access Token)
- Загрузка binary assets из `dist/` директории

## API
- POST /repos/{owner}/{repo}/releases — создать релиз
- GET /repos/{owner}/{repo}/releases — список релизов
- POST /repos/{owner}/{repo}/releases/{id}/assets — загрузить ассет
- Формат аутентификации: `Authorization: Bearer <token>`
- Accept header: `application/vnd.github+json`

## Архитектура
- `gh_release/api.py` — HTTP-клиент (httpx, Bearer auth, pagination, rate-limit handling)
- `gh_release/release.py` — создание/список релизов
- `gh_release/changelog.py` — парсинг CHANGELOG.md (Keep a Changelog формат)
- `gh_release/cli.py` — argparse: publish, list, --dry-run, --repo, --owner
- Тесты с mock HTTP (pytest + httpx mock или responses)

## Поиск
API GitHub меняется — используй `web_search` или `web_learn` чтобы найти актуальную докуменацию:
`site:docs.github.com REST API releases`
