from __future__ import annotations

from pathlib import Path

from code_scalpel.tools.files import list_files, read_file


def test_list_files_basic(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x")
    (tmp_path / "b.py").write_text("y")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.py").write_text("z")

    files = list_files(tmp_path)
    names = [str(f) for f in files]
    assert "a.py" in names
    assert "b.py" in names
    assert "sub/c.py" in names


def test_list_files_respects_gitignore(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("*.log\nbuild/\n")
    (tmp_path / "main.py").write_text("x")
    (tmp_path / "debug.log").write_text("log")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "out.py").write_text("out")

    files = list_files(tmp_path)
    names = [str(f) for f in files]
    assert "main.py" in names
    assert "debug.log" not in names
    assert "build/out.py" not in names


def test_list_files_excludes_git_dir(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("git config")
    (tmp_path / "main.py").write_text("x")

    files = list_files(tmp_path)
    names = [str(f) for f in files]
    assert not any(".git" in n for n in names)
    assert "main.py" in names


def test_list_files_excludes_hidden_dirs(tmp_path: Path) -> None:
    """Hidden directories like .claude/ or .vscode/ must not leak into context."""
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("{}")
    (tmp_path / ".vscode").mkdir()
    (tmp_path / ".vscode" / "tasks.json").write_text("{}")
    (tmp_path / "main.py").write_text("x")

    files = list_files(tmp_path)
    names = [str(f) for f in files]
    assert not any(".claude" in n for n in names)
    assert not any(".vscode" in n for n in names)
    assert "main.py" in names


def test_list_files_max_files(tmp_path: Path) -> None:
    for i in range(10):
        (tmp_path / f"f{i}.py").write_text("x")

    files = list_files(tmp_path, max_files=3)
    assert len(files) == 3


def test_read_file_has_line_numbers(tmp_path: Path) -> None:
    f = tmp_path / "code.py"
    f.write_text("def hello():\n    pass\n")

    content = read_file(f, max_lines=400)
    assert "1  def hello():" in content
    assert "2      pass" in content
    assert "more lines" not in content


def test_read_file_truncates(tmp_path: Path) -> None:
    f = tmp_path / "big.py"
    f.write_text("\n".join(f"line {i}" for i in range(100)))

    content = read_file(f, max_lines=10)
    assert "1  line 0" in content
    assert "10  line 9" in content
    assert "line 10" not in content
    assert "90 more lines" in content
    assert "100 total" in content


def test_read_file_exact_limit(tmp_path: Path) -> None:
    f = tmp_path / "exact.py"
    f.write_text("\n".join("x" for _ in range(5)))

    content = read_file(f, max_lines=5)
    assert "more lines" not in content


def test_read_file_line_number_width(tmp_path: Path) -> None:
    f = tmp_path / "wide.py"
    f.write_text("\n".join("x" for _ in range(100)))

    content = read_file(f, max_lines=400)
    # line numbers should be right-aligned with consistent width
    assert "  1  x" in content
    assert "100  x" in content
