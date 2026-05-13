def mark_done(self, todo_id: int) -> Todo | None:
        items = self._read()
        for item in items:
            if item.id == todo_id:
                item.done = True
                self._write(items)
                return item
        return None