import aiosqlite

DB_PATH = "bookclub.db"


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS books (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT    NOT NULL,
                author      TEXT    NOT NULL,
                description TEXT    NOT NULL DEFAULT '',
                votes       INTEGER NOT NULL DEFAULT 0,
                is_current  INTEGER NOT NULL DEFAULT 0
            )
        """)
        await db.commit()


async def add_book(title: str, author: str, description: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "INSERT INTO books (title, author, description) VALUES (?, ?, ?)",
            (title, author, description),
        )
        await db.commit()
        return cursor.lastrowid


async def get_all_books() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, title, author, description, votes, is_current FROM books"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_book_by_id(book_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, title, author, description, votes, is_current FROM books WHERE id = ?",
            (book_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def vote_for_book(book_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE books SET votes = votes + 1 WHERE id = ?",
            (book_id,),
        )
        await db.commit()


async def get_current_book() -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, title, author, description, votes, is_current FROM books WHERE is_current = 1"
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def set_current_book(book_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE books SET is_current = 0")
        await db.execute(
            "UPDATE books SET is_current = 1 WHERE id = ?",
            (book_id,),
        )
        await db.commit()


async def reset_votes() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE books SET votes = 0")
        await db.commit()
