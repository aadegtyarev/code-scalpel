#!/usr/bin/env python
import json
import sys
import os

def add_note(note):
    notes = load_notes()
    notes.append(note)
    save_notes(notes)

def list_notes():
    notes = load_notes()
    for note in notes:
        print(note)

def search_notes(query):
    notes = load_notes()
    for note in notes:
        if query.lower() in note.lower():
            print(note)

def delete_note(index):
    notes = load_notes()
    if 0 <= index < len(notes):
        del notes[index]
        save_notes(notes)
    else:
        print("Invalid index")

def load_notes():
    if os.path.exists('notes.json'):
        with open('notes.json', 'r') as f:
            return json.load(f)
    return []

def save_notes(notes):
    with open('notes.json', 'w') as f:
        json.dump(notes, f, indent=4)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: notes.py [add|list|search|delete] [args]")
        sys.exit(1)

    command = sys.argv[1]
    args = sys.argv[2:] if len(sys.argv) > 2 else []

    if command == "add":
        add_note(" ".join(args))
    elif command == "list":
        list_notes()
    elif command == "search":
        search_notes(" ".join(args))
    elif command == "delete":
        delete_note(int(args[0]))
    else:
        print(f"Unknown command: {command}")