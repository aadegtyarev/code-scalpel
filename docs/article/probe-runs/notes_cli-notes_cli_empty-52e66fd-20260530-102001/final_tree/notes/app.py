import json

class NotesApp:
    def __init__(self, storage_path='notes.json'):
        self.storage_path = storage_path
        self.notes = self.load_notes()

    def load_notes(self):
        try:
            with open(self.storage_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return []

    def save_notes(self):
        with open(self.storage_path, 'w') as f:
            json.dump(self.notes, f, indent=4)

    def add_note(self, note):
        self.notes.append(note)
        self.save_notes()

    def list_notes(self):
        return self.notes

    def search_notes(self, keyword):
        return [note for note in self.notes if keyword.lower() in note.lower()]

    def delete_note(self, index):
        if 0 <= index < len(self.notes):
            del self.notes[index]
            self.save_notes()
