import json

class NoteStorage:
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

    def add_note(self, text):
        note = {'id': len(self.notes) + 1, 'text': text}
        self.notes.append(note)
        self.save()

    def list_notes(self):
        return self.notes

    def search_notes(self, query):
        return [note for note in self.notes if query.lower() in note['text'].lower()]

    def delete_note(self, note_id):
        self.notes = [note for note in self.notes if note['id'] != note_id]
        self.save()
