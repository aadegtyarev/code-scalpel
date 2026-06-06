import json
import os
from typing import List, Dict, Any

class Storage:
    def __init__(self, file_path: str):
        self.file_path = file_path

    def _load_all(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.file_path):
            return []
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []

    def _save_all(self, data: List[Dict[str, Any]]) -> None:
        with open(self.file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def get_all(self) -> List[Dict[str, Any]]:
        return self._load_all()

    def add(self, note: Dict[str, Any]) -> None:
        notes = self._load_all()
        notes.append(note)
        self._save_all(notes)

    def delete(self, note_id: int) -> bool:
        notes = self._load_all()
        initial_count = len(notes)
        notes = [n for n in notes if n.get('id') != note_id]
        if len(notes) < initial_count:
            self._save_all(notes)
            return True
        return False
