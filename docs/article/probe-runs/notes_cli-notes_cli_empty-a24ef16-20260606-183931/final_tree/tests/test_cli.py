import subprocess
from pathlib import Path

def setup_module(module):
    if Path('notes.json').exists():
        Path('notes.json').unlink()

def test_add(tmp_path):
    result = subprocess.run(['python', 'cli.py', 'add', 'Test note 1'], capture_output=True, text=True)
    assert result.returncode == 0
    notes = list(Path('notes.json').read_text().strip().split('\n'))
    assert len(notes) == 1
    assert notes[0] == 'Test note 1'

def test_list(tmp_path):
    subprocess.run(['python', 'cli.py', 'add', 'Test note 2'], capture_output=True, text=True)
    result = subprocess.run(['python', 'cli.py', 'list'], capture_output=True, text=True)
    assert result.returncode == 0
    notes = result.stdout.strip().split('\n')
    assert len(notes) == 1
    assert notes[0] == 'Test note 2'

def test_search(tmp_path):
    subprocess.run(['python', 'cli.py', 'add', 'Test note 3'], capture_output=True, text=True)
    result = subprocess.run(['python', 'cli.py', 'search', 'test'], capture_output=True, text=True)
    assert result.returncode == 0
    notes = result.stdout.strip().split('\n')
    assert len(notes) == 1
    assert notes[0] == 'Test note 3'

def test_delete(tmp_path):
    subprocess.run(['python', 'cli.py', 'add', 'Test note 4'], capture_output=True, text=True)
    result = subprocess.run(['python', 'cli.py', 'delete', '0'], capture_output=True, text=True)
    assert result.returncode == 0
    notes = list(Path('notes.json').read_text().strip().split('\n'))
    assert len(notes) == 0