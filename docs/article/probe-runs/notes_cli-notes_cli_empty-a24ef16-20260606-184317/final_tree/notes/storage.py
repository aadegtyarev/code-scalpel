import json

class Storage:
    def __init__(self, filename='notes.json'):
        self.filename = filename
        try:
            with open(self.filename, 'r') as file:
                self.notes = json.load(file)
        except FileNotFoundError:
            self.notes = []

    def add_note(self, text):
        self.notes.append(text)
        self._save()

    def list_notes(self):
        return self.notes

    def search_notes(self, keyword):
        return [note for note in self.notes if keyword.lower() in note.lower()]

    def delete_note(self, index):
        if 0 <= index < len(self.notes):
            del self.notes[index]
            self._save()

    def _save(self):
        with open(self.filename, 'w') as file:
            json.dump(self.notes, file, indent=4)
