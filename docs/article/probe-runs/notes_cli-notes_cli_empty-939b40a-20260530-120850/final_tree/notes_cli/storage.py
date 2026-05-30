import json
from datetime import datetime
from notes_cli.note import Note

class JSONStorage:
    def __init__(self, file_path):
        self.file_path = file_path
        self.load_notes()

    def load_notes(self):
        try:
            with open(self.file_path, 'r') as f:
                notes_data = json.load(f)
                self.notes = [Note(note['id'], note['content']) for note in notes_data]
                if self.notes:
                    self.next_id = max(note.id for note in self.notes) + 1
                else:
                    self.next_id = 1
        except FileNotFoundError:
            self.notes = []
            self.next_id = 1

    def save_notes(self):
        with open(self.file_path, 'w') as f:
            notes_data = [{'id': note.id, 'content': note.content} for note in self.notes]
            json.dump(notes_data, f)

    def add(self, content):
        new_note = Note(self.next_id, content)
        self.next_id += 1
        self.notes.append(new_note)
        self.save_notes()
        return new_note

    def get_all(self):
        return self.notes

    def search(self, query):
        return [note for note in self.notes if query.lower() in note.content.lower()]

    def delete(self, note_id):
        self.notes = [note for note in self.notes if note.id != note_id]
        self.save_notes()
