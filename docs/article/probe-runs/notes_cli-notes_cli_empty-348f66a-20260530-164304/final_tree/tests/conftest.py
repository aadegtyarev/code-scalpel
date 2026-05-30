import pytest
from notes.storage import get_storage_path
def pytest_sessionstart(session):
    storage_path = get_storage_path()
    if storage_path.exists():
        storage_path.unlink()