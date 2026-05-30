import json
import os

class NotesManager:
    def __init__(self, storage_path='notes.json'):
        self.storage_path = storage_path
        if not os.path.exists(storage_path):
            with open(storage_path, 'w') as f:
                json.dump([], f)

    def add(self, note):
        notes = self._load_notes()
        notes.append({'id': len(notes) + 1, 'text': note})
        self._save_notes(notes)

    def list(self):
        return self._load_notes()

    def search(self, keyword):
        notes = self._load_notes()
        return [note for note in notes if keyword.lower() in note['text'].lower()]

    def delete(self, note_id):
        notes = self._load_notes()
        notes = [note for note in notes if note['id'] != note_id]
        self._save_notes(notes)

    def _load_notes(self):
        with open(self.storage_path, 'r') as f:
            return json.load(f)

    def _save_notes(self, notes):
        with open(self.storage_path, 'w') as f:
            json.dump(notes, f)