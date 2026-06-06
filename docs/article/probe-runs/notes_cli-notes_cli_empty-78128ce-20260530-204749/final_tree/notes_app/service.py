import datetime
from typing import List, Dict, Any, Optional
from notes_app.storage import Storage

class NoteService:
    def __init__(self, storage: Storage):
        self.storage = storage

    def add_note(self, text: str) -> Dict[str, Any]:
        if not text.strip():
            raise ValueError("Note text cannot be empty")
        
        notes = self.storage.get_all()
        new_id = max([n['id'] for n in notes], default=0) + 1
        
        new_note = {
            "id": new_id,
            "text": text.strip(),
            "created_at": datetime.datetime.now().isoformat()
        }
        self.storage.add(new_note)
        return new_note

    def list_notes(self) -> List[Dict[str, Any]]:
        return self.storage.get_all()

    def search_notes(self, query: str) -> List[Dict[str, Any]]:
        if not query.strip():
            return self.list_notes()
        
        query = query.lower()
        return [
            n for n in self.storage.get_all() 
            if query in n['text'].lower()
        ]

    def delete_note(self, note_id: int) -> bool:
        return self.storage.delete(note_id)
