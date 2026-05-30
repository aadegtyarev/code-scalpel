import json
from main import search, add

def test_search_notes():
    add('Test note 1')
    add('Another test note')
    results = search('test')
    assert len(results) == 2
    assert 'Test note 1' in results
    assert 'Another test note' in results
