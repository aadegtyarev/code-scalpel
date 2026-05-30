import json

class JsonStorage:
    def __init__(self, filename):
        self.filename = filename

    def save(self, notes):
        with open(self.filename, 'w') as f:
            json.dump(notes, f)

    def load(self):
        try:
            with open(self.filename, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return []