import unittest
import json
from notes.cli import add_note, list_notes, search_notes, delete_note, load_notes

class TestNotesCLI(unittest.TestCase):
    def setUp(self):
        self.notes = []
        with open('notes.json', 'w') as f:
            json.dump([], f)

    def test_add_note(self):
        add_note('Test note 1')
        notes = load_notes()
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0], 'Test note 1')

    def test_list_notes(self):
        add_note('Test note 2')
        output = list_notes()
        self.assertIn('Test note 2', output)

    def test_search_notes(self):
        add_note('Test note 3')
        results = search_notes('Test')
        self.assertIn('Test note 3', results)

    def test_delete_note(self):
        add_note('Test note 4')
        delete_note(0)
        notes = load_notes()
        self.assertEqual(len(notes), 0)

if __name__ == '__main__':
    unittest.main()