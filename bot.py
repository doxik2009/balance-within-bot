import asyncio
import os
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types.input_file import FSInputFile

TOKEN_ENV = "BOT_TOKEN"

DECKS = {
    "state": {
        "title": "СОСТОЯНИЕ",
        "folder": "Состояние",
        "back": "assets/state/back.png",
    },
    "release": {
        "title": "ОТПУСКАНИЕ",
        "folder": "ОТПУСКАНИЕ",
        "back": "assets/release/back.png",
    },
    "resource": {
        "title": "РЕСУРС",
        "folder": "РЕСУРС",
        "back": "assets/resource/back.png",
    },
}

PAGE_SIZE = 9


@dataclass
class PlayerState:
    deck: Optional[str] = None
    page: int = 0


PLAYERS: Dict[int, PlayerState] = {}


def get_player(uid: int) -> PlayerState:
    if uid not in PLAYERS:
        PLAYERS[uid] = PlayerState()
    return PLAYERS[uid]


def get_cards(folder: str):
    path = Path(folder)
    return sorted(path.glob("*.png"))


def kb_decks():
    kb = InlineKeyboardBuilder()
    for key, d in DECKS.items():
        kb.button(text=d["title"], callback_data=f"deck:{key}")
    kb.adjust(1)
    return kb.as_markup()


def kb_cards(deck_key: str, page: int, total: int):
    kb = InlineKeyboardBuilder()
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)

    for i in range(start, end):
        kb.button(text=f"🂠 {i - start + 1}", callback_data=f"pick:{deck_key}:{i}:{page}")

    if page > 0:
        kb.button(text="◀️", callback_data=f"page:{deck_key}:{page-1}")
    if end < total:
        kb.button(text="▶️", callback_data=f"page:{deck_key}:{page+1}")

    kb.adjust(3)
    return kb.as_markup()


async def main():
    bot = Bot(os.environ[TOKEN_ENV])
    dp = Dispatcher()

    @dp.message(CommandStart())
    async def start(m: Message):
        await m.answer("✨ Выбери колоду", reply_markup=kb_decks())

    @dp.callback_query(F.data.startswith("deck:"))
    async def show_deck(q: CallbackQuery):
        deck_key = q.data.split(":")[1]
        state = get_player(q.from_user.id)
        state.deck = deck_key
        state.page = 0

        cards = get_cards(DECKS[deck_key]["folder"])
        back_path = DECKS[deck_key]["back"]

        await q.message.delete()
        await q.message.answer_photo(
            photo=FSInputFile(back_path),
            caption=f"{DECKS[deck_key]['title']}\nВыбери карту",
            reply_markup=kb_cards(deck_key, state.page, len(cards))
        )

    @dp.callback_query(F.data.startswith("page:"))
    async def change_page(q: CallbackQuery):
        _, deck_key, page = q.data.split(":")
        page = int(page)
        state = get_player(q.from_user.id)
        state.page = page

        cards = get_cards(DECKS[deck_key]["folder"])

        await q.message.edit_reply_markup(
            reply_markup=kb_cards(deck_key, page, len(cards))
        )

    @dp.callback_query(F.data.startswith("pick:"))
    async def open_card(q: CallbackQuery):
        _, deck_key, idx, page = q.data.split(":")
        idx = int(idx)

        cards = get_cards(DECKS[deck_key]["folder"])
        card = cards[idx]

        await q.message.answer_photo(photo=FSInputFile(card))

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
