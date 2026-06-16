"""Тесты для извлечения ссылок из .md файлов."""

from pathlib import Path

import pytest

from link_parser import find_md_files, extract_links_from_text, extract_links_from_file


def test_find_md_files(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.md").write_text("")
    (tmp_path / "sub" / "c.txt").write_text("")
    files = find_md_files(str(tmp_path))
    assert len(files) == 2
    assert any(f.endswith("a.md") for f in files)
    assert any(f.endswith("sub/b.md") for f in files)


def test_find_md_files_ignores_hidden_dirs(tmp_path: Path) -> None:
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / "x.md").write_text("")
    files = find_md_files(str(tmp_path))
    assert files == []


def test_extract_inline_link() -> None:
    text = "See [Python](https://python.org) for details."
    links = extract_links_from_text(text, "test.md")
    assert len(links) == 1
    assert links[0]["url"] == "https://python.org"
    assert links[0]["type"] == "inline"
    assert links[0]["line"] == 1


def test_extract_multiple_inline_links() -> None:
    text = "[A](https://a.com) and [B](https://b.org) and [C](https://c.net)"
    links = extract_links_from_text(text, "test.md")
    assert len(links) == 3
    assert links[0]["url"] == "https://a.com"
    assert links[1]["url"] == "https://b.org"
    assert links[2]["url"] == "https://c.net"


def test_extract_autolink() -> None:
    text = "Visit <https://python.org> today."
    links = extract_links_from_text(text, "test.md")
    assert len(links) == 1
    assert links[0]["url"] == "https://python.org"
    assert links[0]["type"] == "autolink"


def test_extract_reference_style() -> None:
    text = "[Python][py] is great.\n\n[py]: https://python.org\n"
    links = extract_links_from_text(text, "test.md")
    assert len(links) == 1
    assert links[0]["url"] == "https://python.org"
    assert links[0]["type"] == "reference"


def test_extract_relative_link() -> None:
    text = "See [local](doc/guide.md) or [root](/index.html)."
    links = extract_links_from_text(text, "test.md")
    assert len(links) == 2
    assert links[0]["url"] == "doc/guide.md"
    assert links[1]["url"] == "/index.html"


def test_ignore_anchor_only() -> None:
    text = "Jump to [section](#intro)."
    links = extract_links_from_text(text, "test.md")
    assert links == []


def test_extract_link_in_code_block() -> None:
    text = "```\n[link](https://example.com)\n```\n"
    links = extract_links_from_text(text, "test.md")
    assert len(links) == 1


def test_extract_image_url() -> None:
    text = "![logo](https://example.com/logo.png)"
    links = extract_links_from_text(text, "test.md")
    assert len(links) == 1
    assert links[0]["url"] == "https://example.com/logo.png"


def test_skip_empty_url() -> None:
    text = "[empty]()"
    links = extract_links_from_text(text, "test.md")
    assert links == []


def test_line_numbers() -> None:
    text = "line1\nline2 [link](https://a.com)\nline3 [link2](https://b.com)"
    links = extract_links_from_text(text, "test.md")
    assert len(links) == 2
    assert links[0]["line"] == 2
    assert links[1]["line"] == 3


def test_extract_from_file(tmp_path: Path) -> None:
    md_file = tmp_path / "test.md"
    md_file.write_text("[Python](https://python.org)\n[PEP](https://peps.python.org)\n")
    links = extract_links_from_file(str(md_file))
    assert len(links) == 2
    assert links[0]["url"] == "https://python.org"
    assert links[1]["url"] == "https://peps.python.org"


def test_cmd_extract_output(capsys: pytest.CaptureFixture) -> None:
    links = extract_links_from_text("[A](https://a.com)", "f.md")
    print("# f.md")
    for link in links:
        print(f"  [{link['type']}] {link['url']}")
    captured = capsys.readouterr()
    assert "# f.md" in captured.out
    assert "https://a.com" in captured.out
