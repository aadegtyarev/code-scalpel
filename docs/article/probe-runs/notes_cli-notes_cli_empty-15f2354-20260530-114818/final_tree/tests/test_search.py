import unittest
import json
from notes.storage import Storage

class TestSearchCommand(unittest.TestCase):
    def setUp(self):
        self.storage = Storage('test_notes.json')
        # Очищаем хранилище перед каждым тестом
        with open('test_notes.json', 'w') as f:
            json.dump([], f)

    def test_search_empty(self):
        results = self.storage.search('query')
        self.assertEqual(len(results), 0)

    def test_search_notes(self):
        self.storage.add('Test Note 1', 'This is the first test note.')
        self.storage.add('Test Note 2', 'This is the second test note.')
        results = self.storage.search('first')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['title'], 'Test Note 1')
        self.assertEqual(results[0]['content'], 'This is the first test note.')

if __name__ == '__main__':
    unittest.main()