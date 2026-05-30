import json

STORAGE_FILE = 'storage.json'

def load_notes():
    try:
        with open(STORAGE_FILE, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        return []

def save_notes(notes):
    with open(STORAGE_FILE, 'w') as file:
        json.dump(notes, file, indent=4)

def add(note):
    notes = load_notes()
    notes.append({'note': note})
    save_notes(notes)


def list_notes():
    notes = load_notes()
    for i, note in enumerate(notes, start=1):
        print(f'{i}. {note['note']}')
    return notes

def search(query):
    notes = load_notes()
    results = [note for note in notes if query.lower() in note['note'].lower()]
    for i, note in enumerate(results, start=1):
        print(f'{i}. {note['note']}')
    return results

def delete(index):
    notes = load_notes()
    if 0 < index <= len(notes):
        del notes[index - 1]
        save_notes(notes)
    else:
        print('Неверный номер заметки.')