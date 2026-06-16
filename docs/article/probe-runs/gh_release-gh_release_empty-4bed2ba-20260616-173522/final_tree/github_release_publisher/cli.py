"""CLI для публикации GitHub-релизов."""

import os
import sys

import click

from github_release_publisher.changelog import parse_changelog
from github_release_publisher.github_client import GitHubClient


def _resolve_repo(repo: str | None) -> str:
    """Репозиторий из аргумента, переменной окружения или ошибка."""
    if repo:
        return repo
    env_repo = os.environ.get("GITHUB_REPOSITORY")
    if env_repo:
        return env_repo
    raise click.UsageError(
        "Укажите --repo или установите GITHUB_REPOSITORY (owner/repo)"
    )


# ---------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------

@click.command()
@click.option("--repo", default=None, help="Репозиторий в формате owner/repo")
@click.option(
    "--changelog",
    default="CHANGELOG.md",
    show_default=True,
    help="Путь к CHANGELOG.md",
    type=click.Path(exists=True, dir_okay=False, readable=True),
)
@click.option(
    "--assets",
    multiple=True,
    default=[],
    help="Файлы для загрузки (можно указать несколько раз)",
    type=click.Path(exists=True, dir_okay=False, readable=True),
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Показать, что будет сделано, без вызова API",
)
@click.pass_context
def publish(ctx, repo, changelog, assets, dry_run):
    """Парсит CHANGELOG.md, создаёт GitHub Release и загружает бинарники."""
    repo_str = _resolve_repo(repo)

    # 1. Парсим changelog
    click.echo(f"📄 Парсинг {changelog}...")
    release_info = parse_changelog(changelog)
    if release_info is None:
        click.echo("❌ Не найдено ни одной записи о версии в CHANGELOG.md", err=True)
        sys.exit(1)

    tag = f"v{release_info['version']}"
    click.echo(f"   Версия: {release_info['version']} ({release_info['date']})")

    # 2. Создаём клиент (может выкинуть ValueError если нет токена)
    try:
        client = ctx.obj.get("client") if ctx.obj else None
        if client is None:
            client = GitHubClient()
    except ValueError as exc:
        click.echo(f"❌ {exc}", err=True)
        sys.exit(1)

    # 3. Создаём релиз
    if dry_run:
        click.echo(f"🔍 [DRY RUN] Создание релиза {tag} в {repo_str}")
        click.echo(f"   Название: {tag}")
        click.echo(f"   Тело релиза:\n{release_info['body']}\n")
    else:
        click.echo(f"🚀 Создание релиза {tag} в {repo_str}...")
        result = client.create_release(
            repo=repo_str,
            tag=tag,
            name=tag,
            body=release_info["body"],
        )
        click.echo(f"   ✅ Релиз создан: {result.get('html_url', '')}")

    # 4. Загружаем asset'ы
    if not assets:
        click.echo("   ⚠️  Нет файлов для загрузки (--assets не указан)")
        return

    for asset_path in assets:
        if dry_run:
            click.echo(f"   [DRY RUN] Загрузка {asset_path}")
        else:
            click.echo(f"   📦 Загрузка {asset_path}...")
            asset = client.upload_asset(result, asset_path)
            click.echo(
                f"      ✅ {asset.get('name', '')} → "
                f"{asset.get('browser_download_url', '')}"
            )


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

@click.command()
@click.option("--repo", default=None, help="Репозиторий в формате owner/repo")
@click.pass_context
def list_releases(ctx, repo):
    """Выводит список опубликованных релизов."""
    repo_str = _resolve_repo(repo)

    try:
        client = ctx.obj.get("client") if ctx.obj else None
        if client is None:
            client = GitHubClient()
    except ValueError as exc:
        click.echo(f"❌ {exc}", err=True)
        sys.exit(1)

    click.echo(f"📋 Релизы {repo_str}:")
    releases = client.list_releases(repo_str)

    if not releases:
        click.echo("   (пусто)")
        return

    for r in releases:
        tag = r.get("tag_name", "?")
        name = r.get("name", "") or tag
        published = r.get("published_at", "")[:10] if r.get("published_at") else ""
        draft = " [черновик]" if r.get("draft") else ""
        prerelease = " [пре-релиз]" if r.get("prerelease") else ""
        click.echo(f"   • {tag}  {name}  ({published}){draft}{prerelease}")


# ---------------------------------------------------------------------------
# Группа (main)
# ---------------------------------------------------------------------------

@click.group()
def cli():
    """GitHub Release Publisher — публикация релизов из CHANGELOG.md."""


cli.add_command(publish)
cli.add_command(list_releases, name="list")


def main():
    cli()
