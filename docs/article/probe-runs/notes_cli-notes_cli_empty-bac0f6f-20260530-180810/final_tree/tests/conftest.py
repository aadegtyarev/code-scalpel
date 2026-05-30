import json
import os
import pytest

def clear_storage():
    storage_path = 'storage.json'
    if os.path.exists(storage_path):
        with open(storage_path, 'w') as f:
            json.dump([], f)

@pytest.fixture(autouse=True)
def setup_teardown():
    clear_storage()
    yield
    clear_storage()