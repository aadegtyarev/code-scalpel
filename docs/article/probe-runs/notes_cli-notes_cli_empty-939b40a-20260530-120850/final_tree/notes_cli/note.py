from datetime import datetime

class Note:
    def __init__(self, id, content):
        self.id = id
        self.content = content
        self.created_at = datetime.now()

    def __str__(self):
        return f"Note(id={self.id}, content='{self.content}', created_at={self.created_at})"