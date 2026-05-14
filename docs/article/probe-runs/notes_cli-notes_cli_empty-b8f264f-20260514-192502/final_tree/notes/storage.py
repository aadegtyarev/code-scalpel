import json

class Storage:
    def __init__(self, filename='notes.json'):
        self.filename = filename
        try:
            with open(self.filename, 'r') as file:
                self.notes = json.load(file)
        except FileNotFoundError:
            self.notes = []

    def add_note(self, note):
        self.notes.append(note)
        with open(self.filename, 'w') as file:
            json.dump(self.notes, file, indent=4)