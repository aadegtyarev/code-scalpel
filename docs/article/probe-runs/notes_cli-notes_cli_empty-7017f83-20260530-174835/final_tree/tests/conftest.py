import json
import os
import pytest

def clear_notes():
    if os.path.exists('notes.json'):
        os.remove('notes.json')

@pytest.fixture(autouse=True)
def setup_notes():
    clear_notes()