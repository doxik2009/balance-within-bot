import asyncio
import os
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message

async def main():
    token = os.environ["BOT_TOKEN"]
    bot = Bot(token)
    dp = Dispatcher()

    @dp.message(CommandStart())
    async def start(m: Message):
        await m.answer("Бот запущен ✅")

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
