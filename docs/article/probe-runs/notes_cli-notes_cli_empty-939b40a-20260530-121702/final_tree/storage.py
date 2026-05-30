import json

def load_notes():
    try:
        with open('notes.json', 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        return []

def save_notes(notes):
    with open('notes.json', 'w') as file:
        json.dump(notes, file, indent=4)

def add_note(note):
    notes = load_notes()
    notes.append(note)
    save_notes(notes)


def get_notes():
    return load_notes()

def search_notes(keyword):
    notes = load_notes()
    return [note for note in notes if keyword.lower() in note.lower()]

def delete_note(index):
    notes = load_notes()
    if 0 <= index < len(notes):
        del notes[index]
        save_notes(notes)
