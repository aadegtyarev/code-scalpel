import json
import os

class NoteStorage:
    def __init__(self, filepath='notes.json'):
        self.filepath = filepath
        if not os.path.exists(filepath):
            with open(filepath, 'w') as f:
                json.dump([], f)

    def load_notes(self):
        with open(self.filepath, 'r') as f:
            return json.load(f)

    def save_notes(self, notes):
        with open(self.filepath, 'w') as f:
            json.dump(notes, f)