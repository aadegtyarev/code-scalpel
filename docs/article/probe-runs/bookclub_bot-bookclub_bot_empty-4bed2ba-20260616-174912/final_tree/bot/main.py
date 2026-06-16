import asyncio
import os

from aiogram import Bot, Dispatcher

from bot.db import init_db
from bot.handlers import router


async def main() -> None:
    token = os.environ["BOT_TOKEN"]

    bot = Bot(token=token)
    dp = Dispatcher()
    dp.include_router(router)

    await init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
