import unittest
import json
from notes.storage import Storage

class TestAddCommand(unittest.TestCase):
    def setUp(self):
        self.storage = Storage('test_notes.json')
        # Очищаем хранилище перед каждым тестом
        with open('test_notes.json', 'w') as f:
            json.dump([], f)

    def test_add_note(self):
        self.storage.add('Test Note', 'This is a test note.')
        notes = self.storage.list()
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]['title'], 'Test Note')
        self.assertEqual(notes[0]['content'], 'This is a test note.')

if __name__ == '__main__':
    unittest.main()