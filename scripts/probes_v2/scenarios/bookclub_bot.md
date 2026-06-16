# Book Club Telegram Bot

Асинхронный Telegram-бот для книжного клуба с голосованием.

## Команды
- /start — приветствие и список команд
- /add_book — добавляет книгу (два шага: автор → название)
- /vote — голосование за книгу (inline-клавиатура с кнопками)
- /next — книга-победитель (наибольшее число голосов)
- /list — список книг с голосами
- /reset_votes — сбросить голоса (только админ по user_id)

## Архитектура
- aiogram 3.x — асинхронный фреймворк
- SQLite через aiosqlite — персистентность (книги, голоса, админы)
- FSM (Finite State Machine) — для многошагового /add_book
- InlineKeyboardMarkup — кнопки голосования с callback_data
- Dockerfile + docker-compose (если есть время)

## Поиск
Используй web_search для актуального API aiogram 3.x:
- aiogram FSM states
- aiogram InlineKeyboard
- aiogram callback handlers
- aiosqlite async usage
