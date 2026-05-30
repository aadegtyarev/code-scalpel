import pytest
from notes.app import NotesApp

def setup_module(module):
    app = NotesApp()
    app.notes = []
    app.save_notes()