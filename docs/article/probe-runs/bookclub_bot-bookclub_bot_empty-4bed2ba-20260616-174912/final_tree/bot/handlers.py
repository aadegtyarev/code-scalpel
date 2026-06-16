from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.db import (
    add_book,
    get_all_books,
    get_current_book,
    reset_votes,
    set_current_book,
    vote_for_book,
)
from bot.states import AddBook

router = Router()


# ── /start ────────────────────────────────────────────────
@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "📚 Добро пожаловать в Книжный клуб!\n\n"
        "Доступные команды:\n"
        "/add_book — добавить новую книгу\n"
        "/vote — проголосовать за книгу\n"
        "/next — выбрать следующую книгу\n"
        "/list — показать все книги\n"
        "/reset_votes — сбросить голоса"
    )


# ── /add_book — FSM ───────────────────────────────────────
@router.message(Command("add_book"))
async def cmd_add_book(message: Message, state: FSMContext) -> None:
    await state.set_state(AddBook.title)
    await message.answer("Введите название книги:")


@router.message(AddBook.title)
async def process_title(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if not text:
        await message.answer("Название не может быть пустым. Попробуйте снова:")
        return
    await state.update_data(title=text)
    await state.set_state(AddBook.author)
    await message.answer("Введите автора книги:")


@router.message(AddBook.author)
async def process_author(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if not text:
        await message.answer("Автор не может быть пустым. Попробуйте снова:")
        return
    await state.update_data(author=text)
    await state.set_state(AddBook.description)
    await message.answer("Введите краткое описание книги:")


@router.message(AddBook.description)
async def process_description(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if not text:
        await message.answer("Описание не может быть пустым. Попробуйте снова:")
        return
    data = await state.get_data()
    book_id = await add_book(
        title=data["title"],
        author=data["author"],
        description=text,
    )
    await state.clear()
    await message.answer(
        f'✅ Книга "{data["title"]}" добавлена! (id {book_id})'
    )


# ── /list ─────────────────────────────────────────────────
@router.message(Command("list"))
async def cmd_list(message: Message) -> None:
    books = await get_all_books()
    if not books:
        await message.answer("Книг пока нет. Добавьте первую через /add_book")
        return

    lines = []
    for b in books:
        current = " 📖" if b["is_current"] else ""
        lines.append(
            f'{b["id"]}. "{b["title"]}" — {b["author"]} — {b["votes"]} голосов{current}'
        )
    await message.answer("Список книг:\n" + "\n".join(lines))


# ── /vote ─────────────────────────────────────────────────
@router.message(Command("vote"))
async def cmd_vote(message: Message) -> None:
    books = await get_all_books()
    if not books:
        await message.answer("Книг пока нет. Сначала добавьте их через /add_book")
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f'{b["title"]} ({b["votes"]})',
                    callback_data=f"vote:{b['id']}",
                )
            ]
            for b in books
        ]
    )
    await message.answer("Голосуйте за книгу месяца:", reply_markup=keyboard)


@router.callback_query(lambda c: c.data and c.data.startswith("vote:"))
async def process_vote(callback: CallbackQuery) -> None:
    book_id = int(callback.data.split(":")[1])
    await vote_for_book(book_id)
    await callback.answer("Голос учтён!", show_alert=False)

    # Обновляем клавиатуру с новыми голосами
    books = await get_all_books()
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f'{b["title"]} ({b["votes"]})',
                    callback_data=f"vote:{b['id']}",
                )
            ]
            for b in books
        ]
    )
    await callback.message.edit_reply_markup(reply_markup=keyboard)


# ── /next ─────────────────────────────────────────────────
@router.message(Command("next"))
async def cmd_next(message: Message) -> None:
    books = await get_all_books()
    if not books:
        await message.answer("Книг пока нет. Добавьте первую через /add_book")
        return

    current = await get_current_book()
    if current is None:
        # Ничего не выбрано — берём первую книгу
        await set_current_book(books[0]["id"])
        await message.answer(
            f'Текущая книга: "{books[0]["title"]}"'
        )
        return

    # Ищем следующую по id
    current_id = current["id"]
    next_book = None
    for b in books:
        if b["id"] > current_id:
            next_book = b
            break

    if next_book is None:
        # Дошли до конца — зацикливаем на первую
        next_book = books[0]

    await set_current_book(next_book["id"])
    await message.answer(
        f'Текущая книга: "{next_book["title"]}"'
    )


# ── /reset_votes ─────────────────────────────────────────
@router.message(Command("reset_votes"))
async def cmd_reset_votes(message: Message) -> None:
    await reset_votes()
    await message.answer("Голоса всех книг сброшены!")
