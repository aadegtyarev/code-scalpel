import json
from pathlib import Path
def main():
    print("Программа для работы с заметками")

def add_note(note):
    notes_path = Path('data/notes.json')
    with open(notes_path, 'r+') as file:
        notes = json.load(file)
        notes.append(note)
        file.seek(0)
        json.dump(notes, file, indent=4)
        file.truncate()

if __name__ == "__main__":
    main()