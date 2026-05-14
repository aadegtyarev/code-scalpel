import json

class Storage:
    def __init__(self, filename='notes.json'):
        self.filename = filename
        self.load_notes()

    def load_notes(self):
        try:
            with open(self.filename, 'r') as file:
                self.notes = json.load(file)
        except FileNotFoundError:
            self.notes = []

    def save_notes(self):
        with open(self.filename, 'w') as file:
            json.dump(self.notes, file, indent=4)

    def add_note(self, note):
        self.notes.append(note)
        self.save_notes()

    def get_notes(self):
        return self.notes

    def search_notes(self, query):
        return [note for note in self.notes if query.lower() in note.lower()]

    def delete_note(self, index):
        if 0 <= index < len(self.notes):
            del self.notes[index]
            self.save_notes()
            return True
        return False