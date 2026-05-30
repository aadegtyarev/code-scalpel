import json

class NoteStorage:
    def __init__(self, filename='notes.json'):
        self.filename = filename
        try:
            with open(self.filename, 'r') as f:
                self.notes = json.load(f)
        except FileNotFoundError:
            self.notes = []

    def add(self, note):
        self.notes.append(note)
        self._save()

    def list(self):
        return self.notes

    def search(self, keyword):
        return [note for note in self.notes if keyword.lower() in note.lower()]

    def delete(self, index):
        if 0 <= index < len(self.notes):
            del self.notes[index]
            self._save()

    def _save(self):
        with open(self.filename, 'w') as f:
            json.dump(self.notes, f, indent=4)