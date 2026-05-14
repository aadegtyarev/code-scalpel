import json

class NotesStorage:
    def __init__(self, filepath='notes.json'):
        self.filepath = filepath
        self.notes = []
        self.load()

    def load(self):
        try:
            with open(self.filepath, 'r') as file:
                self.notes = json.load(file)
        except FileNotFoundError:
            self.notes = []

    def save(self):
        with open(self.filepath, 'w') as file:
            json.dump(self.notes, file, indent=4)

    def add(self, note):
        if not note.strip():
            raise ValueError('Note cannot be empty')
        self.notes.append(note)
        self.save()

    def list(self):
        return self.notes

    def search(self, query):
        return [note for note in self.notes if query.lower() in note.lower()]

    def delete(self, index):
        if 0 <= index < len(self.notes):
            del self.notes[index]
            self.save()
        else:
            raise IndexError('Note index out of range')