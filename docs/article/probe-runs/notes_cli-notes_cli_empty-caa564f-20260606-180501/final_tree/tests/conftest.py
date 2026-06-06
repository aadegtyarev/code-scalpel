import os
import pytest
from notes import delete, list_notes

def clear_storage():
    storage_path = 'storage.json'
    if os.path.exists(storage_path):
        os.remove(storage_path)

@pytest.fixture(autouse=True)
def setup_teardown():
    clear_storage()
    yield
    clear_storage()