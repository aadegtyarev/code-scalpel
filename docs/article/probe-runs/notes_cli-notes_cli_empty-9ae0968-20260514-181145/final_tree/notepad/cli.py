from .storage import Storage
class NotepadCLI:
    def __init__(self):
        self.storage = Storage()

    def add(self, note):
        self.storage.add_note(note)

    def list(self):
        return self.storage.get_notes()

    def search(self, keyword):
        return [note for note in self.storage.get_notes() if keyword.lower() in note.lower()]

    def delete(self, index):
        notes = self.storage.get_notes()
        if 1 <= index <= len(notes):
            del notes[index - 1]
            self.storage.save_notes()
