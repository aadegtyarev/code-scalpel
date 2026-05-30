import pytest
from src.storage import JsonStorage
def test_save_load():
    storage = JsonStorage('test_storage.json')
    storage.save(['Note 1', 'Note 2'])
    loaded_notes = storage.load()
    assert loaded_notes == ['Note 1', 'Note 2']