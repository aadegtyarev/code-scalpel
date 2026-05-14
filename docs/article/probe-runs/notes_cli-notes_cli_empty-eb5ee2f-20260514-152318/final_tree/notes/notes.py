from .storage import save, load

def add(note):
    notes = load()
    notes.append({'id': len(notes) + 1, 'note': note})
    save(notes)

def list():
    return load()

def search(query):
    notes = load()
    return [note for note in notes if query.lower() in note['note'].lower()]

def delete(id):
    notes = load()
    updated_notes = [note for note in notes if note['id'] != id]
    save(updated_notes)