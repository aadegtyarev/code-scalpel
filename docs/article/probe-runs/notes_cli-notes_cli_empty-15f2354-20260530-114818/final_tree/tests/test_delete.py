import unittest
import json
from notes.storage import Storage

class TestDeleteCommand(unittest.TestCase):
    def setUp(self):
        self.storage = Storage('test_notes.json')
        # Очищаем хранилище перед каждым тестом
        with open('test_notes.json', 'w') as f:
            json.dump([], f)

    def test_delete_empty(self):
        with self.assertRaises(IndexError):
            self.storage.delete(0)

    def test_delete_note(self):
        self.storage.add('Test Note 1', 'This is the first test note.')
        self.storage.add('Test Note 2', 'This is the second test note.')
        notes = self.storage.list()
        self.assertEqual(len(notes), 2)
        self.storage.delete(0)
        updated_notes = self.storage.list()
        self.assertEqual(len(updated_notes), 1)
        self.assertEqual(updated_notes[0]['title'], 'Test Note 2')

if __name__ == '__main__':
    unittest.main()