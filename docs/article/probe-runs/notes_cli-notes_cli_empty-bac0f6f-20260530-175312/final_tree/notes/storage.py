import json
import os

class Storage:
    def __init__(self, filepath='notes.json'):
        self.filepath = filepath
        if not os.path.exists(filepath):
            with open(filepath, 'w') as f:
                json.dump([], f)

    def add(self, note):
        notes = self._load()
        notes.append(note)
        self._save(notes)

    def list(self):
        return self._load()

    def search(self, keyword):
        notes = self._load()
        return [note for note in notes if keyword.lower() in note.lower()]

    def delete(self, index):
        notes = self._load()
        if 0 <= index < len(notes):
            del notes[index]
            self._save(notes)

    def _load(self):
        with open(self.filepath, 'r') as f:
            return json.load(f)

    def _save(self, notes):
        with open(self.filepath, 'w') as f:
            json.dump(notes, f)