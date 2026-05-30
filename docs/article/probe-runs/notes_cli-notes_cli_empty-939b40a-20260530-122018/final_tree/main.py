#!/usr/bin/env python

import json

def add_note(note):
    with open('notes.json', 'r') as file:
        notes = json.load(file)
    notes.append(note)
    with open('notes.json', 'w') as file:
        json.dump(notes, file, indent=4)

def list_notes():
    with open('notes.json', 'r') as file:
        notes = json.load(file)
    for i, note in enumerate(notes):
        print(f'{i}: {note}')

def search_notes(keyword):
    with open('notes.json', 'r') as file:
        notes = json.load(file)
    for i, note in enumerate(notes):
        if keyword.lower() in note.lower():
            print(f'{i}: {note}')

def delete_note(index):
    with open('notes.json', 'r') as file:
        notes = json.load(file)
    if 0 <= index < len(notes):
        del notes[index]
        with open('notes.json', 'w') as file:
            json.dump(notes, file, indent=4)
    else:
        print('Неверный индекс заметки')

if __name__ == "__main__":
    import sys
    command = sys.argv[1]
    if command == 'add':
        add_note(sys.argv[2])
    elif command == 'list':
        list_notes()
    elif command == 'search':
        search_notes(sys.argv[2])
    elif command == 'delete':
        delete_note(int(sys.argv[2]))
    else:
        print('Неизвестная команда')