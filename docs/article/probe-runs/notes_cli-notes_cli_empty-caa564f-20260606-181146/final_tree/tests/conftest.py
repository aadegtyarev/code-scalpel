import pytest
import os

def clear_notes_json():
    if os.path.exists("notes.json"):
        os.remove("notes.json")

@pytest.fixture(autouse=True)
def setup_tests():
    clear_notes_json()