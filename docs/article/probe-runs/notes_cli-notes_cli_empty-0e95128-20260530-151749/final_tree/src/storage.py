import json
from src.note import Note

class Storage:
    def __init__(self, file_path='notes.json'):
        self.file_path = file_path
        self.notes = []
        self.load()

    def load(self):
        try:
            with open(self.file_path, 'r') as f:
                data = json.load(f)
                self.notes = [Note(note['text']) for note in data]
        except FileNotFoundError:
            pass

    def save(self):
        with open(self.file_path, 'w') as f:
            json.dump([{'text': note.text} for note in self.notes], f, indent=4)

    def add_note(self, text):
        note = Note(text)
        self.notes.append(note)
        self.save()

    def list_notes(self):
        return [note.text for note in self.notes]

    def search_notes(self, keyword):
        return [note.text for note in self.notes if keyword.lower() in note.text.lower()]

    def delete_note(self, index):
        if 0 <= index < len(self.notes):
            del self.notes[index]
            self.save()
