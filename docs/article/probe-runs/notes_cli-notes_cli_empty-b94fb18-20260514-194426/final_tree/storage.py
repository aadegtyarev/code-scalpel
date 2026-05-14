import json
import os
class NoteStorage:
    def __init__(self, filename='notes.json'):
        self.filename = filename
        if not os.path.exists(filename):
            with open(filename, 'w') as f:
                json.dump([], f)

    def add_note(self, note):
        notes = self._load_notes()
        notes.append(note)
        self._save_notes(notes)

    def get_notes(self):
        return self._load_notes()

    def search_notes(self, query):
        notes = self._load_notes()
        return [note for note in notes if query.lower() in note.lower()]

    def delete_note(self, note_id):
        notes = self._load_notes()
        if 0 <= note_id < len(notes):
            del notes[note_id]
            self._save_notes(notes)

    def _load_notes(self):
        with open(self.filename, 'r') as f:
            return json.load(f)

    def _save_notes(self, notes):
        with open(self.filename, 'w') as f:
            json.dump(notes, f)