import json
import os
import tempfile

class Storage:
    def __init__(self, filepath=None):
        if filepath is None:
            fd, self.filepath = tempfile.mkstemp()
            os.close(fd)
            with open(self.filepath, 'w') as f:
                json.dump([], f)
        else:
            self.filepath = filepath
            if not os.path.exists(self.filepath):
                with open(self.filepath, 'w') as f:
                    json.dump([], f)

    def add(self, text):
        notes = self._load_notes()
        note_id = len(notes) + 1
        notes.append({'id': note_id, 'text': text})
        self._save_notes(notes)
        return note_id

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
        with open(self.filepath, 'r') as f:
            return json.load(f)

    def _save_notes(self, notes):
        with open(self.filepath, 'w') as f:
            json.dump(notes, f)