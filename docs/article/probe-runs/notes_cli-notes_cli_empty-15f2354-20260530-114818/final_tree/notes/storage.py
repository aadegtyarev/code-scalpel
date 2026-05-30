import json
import os

class Storage:
    def __init__(self, filename='notes.json'):
        self.filename = filename
        if not os.path.exists(filename):
            with open(filename, 'w') as f:
                json.dump([], f)

    def add(self, title, content):
        notes = self._load_notes()
        note = {'title': title, 'content': content}
        notes.append(note)
        self._save_notes(notes)

    def list(self):
        return self._load_notes()

    def search(self, query):
        notes = self._load_notes()
        return [note for note in notes if query.lower() in note['title'].lower() or query.lower() in note['content'].lower()]

    def delete(self, index):
        notes = self._load_notes()
        if 0 <= index < len(notes):
            del notes[index]
            self._save_notes(notes)

    def _load_notes(self):
        with open(self.filename, 'r') as f:
            return json.load(f)

    def _save_notes(self, notes):
        with open(self.filename, 'w') as f:
            json.dump(notes, f, indent=4)