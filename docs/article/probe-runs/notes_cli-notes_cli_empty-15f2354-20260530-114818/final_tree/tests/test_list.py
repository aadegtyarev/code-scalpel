import unittest
import json
from notes.storage import Storage

class TestListCommand(unittest.TestCase):
    def setUp(self):
        self.storage = Storage('test_notes.json')
        # Очищаем хранилище перед каждым тестом
        with open('test_notes.json', 'w') as f:
            json.dump([], f)

    def test_list_empty(self):
        notes = self.storage.list()
        self.assertEqual(len(notes), 0)

    def test_list_notes(self):
        self.storage.add('Test Note 1', 'This is the first test note.')
        self.storage.add('Test Note 2', 'This is the second test note.')
        notes = self.storage.list()
        self.assertEqual(len(notes), 2)
        self.assertEqual(notes[0]['title'], 'Test Note 1')
        self.assertEqual(notes[0]['content'], 'This is the first test note.')
        self.assertEqual(notes[1]['title'], 'Test Note 2')
        self.assertEqual(notes[1]['content'], 'This is the second test note.')

if __name__ == '__main__':
    unittest.main()