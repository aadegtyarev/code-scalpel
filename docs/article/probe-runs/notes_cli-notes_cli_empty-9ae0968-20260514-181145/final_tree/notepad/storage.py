import json
class Storage:
    def __init__(self, filename='notes.json'):
        self.filename = filename
        try:
            with open(self.filename, 'r') as f:
                self.notes = json.load(f)
        except FileNotFoundError:
            self.notes = []

    def save_notes(self):
        with open(self.filename, 'w') as f:
            json.dump(self.notes, f)

    def add_note(self, note):
        self.notes.append(note)
        self.save_notes()

    def get_notes(self):
        return self.notes