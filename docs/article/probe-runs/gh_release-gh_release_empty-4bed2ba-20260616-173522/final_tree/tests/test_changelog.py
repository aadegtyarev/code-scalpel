"""Tests for CHANGELOG.md parser."""

from pathlib import Path

from github_release_publisher.changelog import parse_changelog


def test_parse_happy_path(tmp_path: Path) -> None:
    """Типичный Keep a Changelog с двумя версиями."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n"
        "\n"
        "## [1.2.0] - 2025-05-15\n"
        "\n"
        "### Added\n"
        "- Новый эндпоинт для поиска\n"
        "- Поддержка пагинации\n"
        "\n"
        "### Fixed\n"
        "- Исправлена утечка соединений\n"
        "\n"
        "## [1.1.0] - 2025-04-01\n"
        "\n"
        "### Added\n"
        "- Первый публичный релиз\n"
    )

    result = parse_changelog(changelog)
    assert result is not None
    assert result["version"] == "1.2.0"
    assert result["date"] == "2025-05-15"
    assert "Новый эндпоинт" in result["body"]
    assert "Исправлена утечка" in result["body"]
    assert "Первый публичный релиз" not in result["body"]


def test_parse_single_version(tmp_path: Path) -> None:
    """Всего одна версия в файле."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "## [0.1.0] - 2024-01-10\n"
        "\n"
        "Initial release.\n"
    )

    result = parse_changelog(changelog)
    assert result is not None
    assert result["version"] == "0.1.0"
    assert result["date"] == "2024-01-10"
    assert result["body"] == "Initial release."


def test_parse_no_version(tmp_path: Path) -> None:
    """Нет ни одного заголовка версии — возвращается None."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\nNothing here yet.\n")

    result = parse_changelog(changelog)
    assert result is None


def test_parse_file_not_exists(tmp_path: Path) -> None:
    """Файл не существует — возвращается None."""
    result = parse_changelog(tmp_path / "nonexistent.md")
    assert result is None


def test_parse_header_without_date_is_none(tmp_path: Path) -> None:
    """Заголовок без ' - date' невалиден — возвращается None."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## [0.2.0]\n\nSomething\n")

    result = parse_changelog(changelog)
    assert result is None


def test_parse_extra_whitespace(tmp_path: Path) -> None:
    """Лишние пробелы вокруг версии и даты."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("##  [  3.0.0  ]  -  2025-06-01  \n\nRelease\n")

    result = parse_changelog(changelog)
    assert result is not None
    assert result["version"] == "3.0.0"
    assert result["date"] == "2025-06-01"
