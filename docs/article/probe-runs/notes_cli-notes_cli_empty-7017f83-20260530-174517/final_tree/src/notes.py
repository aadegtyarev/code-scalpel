import json
from src.storage import JsonStorage
class Notes:
    def __init__(self, storage):
        self.storage = storage
        self.notes = self.storage.load()

    def add(self, text):
        self.notes.append(text)
        self.storage.save(self.notes)

    def list(self):
        return self.notes

    def search(self, keyword):
        return [note for note in self.notes if keyword.lower() in note.lower()]

    def delete(self, index):
        if 0 <= index < len(self.notes):
            del self.notes[index]
            self.storage.save(self.notes)