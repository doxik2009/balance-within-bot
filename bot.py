import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Any

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

TOKEN_ENV = "BOT_TOKEN"

# Ключи колод (внутренние), чтобы не зависеть от русских названий
DECKS = {
    "state": {"title": "СОСТОЯНИЕ"},
    "release": {"title": "ОТПУСКАНИЕ"},
    "resource": {"title": "РЕСУРС"},
}
DECK_ORDER = ["state", "release", "resource"]
PAGE_SIZE = 9

# Файл, куда бот сохраняет file_id
STORE_PATH = Path("file_ids.json")


def load_store() -> Dict[str, Any]:
    if STORE_PATH.exists():
        try:
            return json.loads(STORE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_store(data: Dict[str, Any]) -> None:
    STORE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


STORE: Dict[str, Any] = load_store()
# Структура STORE:
# {
#   "backs": {"state": "file_id", "release": "...", "resource": "..."},
#   "cards": {"state": {"01": "file_id", ...}, "release": {...}, "resource": {...}}
# }


def ensure_store_shape():
    STORE.setdefault("backs", {})
    STORE.setdefault("cards", {})
    for dk in DECKS.keys():
        STORE["cards"].setdefault(dk, {})


ensure_store_shape()
save_store(STORE)


@dataclass
class PlayerState:
    mode: Optional[str] = None  # "self" или "host"
    deck: Optional[str] = None
    page: int = 0


PLAYERS: Dict[int, PlayerState] = {}


def get_player(uid: int) -> PlayerState:
    if uid not in PLAYERS:
        PLAYERS[uid] = PlayerState()
    return PLAYERS[uid]


def kb_mode():
    kb = InlineKeyboardBuilder()
    kb.button(text="🧘‍♀️ Для себя", callback_data="mode:self")
    kb.button(text="🤍 С ведущим", callback_data="mode:host")
    kb.adjust(1)
    return kb.as_markup()


def kb_decks():
    kb = InlineKeyboardBuilder()
    kb.button(text="🟣 Состояние", callback_data="deck:state")
    kb.button(text="🟡 Отпускание", callback_data="deck:release")
    kb.button(text="🟢 Ресурс", callback_data="deck:resource")
    kb.button(text="🔄 Сменить режим", callback_data="go:mode")
    kb.adjust(1)
    return kb.as_markup()


def kb_cards(deck_key: str, page: int, total: int):
    kb = InlineKeyboardBuilder()
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)

    # 9 кнопок
    for i in range(start, end):
        kb.button(text=f"🂠 {i - start + 1}", callback_data=f"pick:{deck_key}:{i}:{page}")

    # навигация
    if page > 0:
        kb.button(text="◀️", callback_data=f"page:{deck_key}:{page-1}")
    if end < total:
        kb.button(text="▶️", callback_data=f"page:{deck_key}:{page+1}")

    kb.button(text="↩️ К колодам", callback_data="go:decks")

    kb.adjust(3)
    return kb.as_markup()


def kb_confirm(deck_key: str, idx: int, page: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Перевернуть", callback_data=f"open:{deck_key}:{idx}:{page}")
    kb.button(text="↩️ Назад", callback_data=f"page:{deck_key}:{page}")
    kb.adjust(1)
    return kb.as_markup()


def kb_after_open(deck_key: str):
    kb = InlineKeyboardBuilder()
    nxt = next_deck(deck_key)
    if nxt:
        kb.button(text="➡️ Следующая колода", callback_data=f"deck:{nxt}")
    kb.button(text="🗂️ К колодам", callback_data="go:decks")
    kb.adjust(1)
    return kb.as_markup()


def next_deck(current: str) -> Optional[str]:
    try:
        i = DECK_ORDER.index(current)
        if i < len(DECK_ORDER) - 1:
            return DECK_ORDER[i + 1]
    except ValueError:
        pass
    return None


def card_num_from_index(idx: int) -> str:
    # idx 0..29 -> "01".."30"
    return f"{idx+1:02d}"


def get_back_file_id(deck_key: str) -> Optional[str]:
    return STORE.get("backs", {}).get(deck_key)


def get_card_file_id(deck_key: str, num: str) -> Optional[str]:
    return STORE.get("cards", {}).get(deck_key, {}).get(num)


def set_back_file_id(deck_key: str, file_id: str):
    STORE["backs"][deck_key] = file_id
    save_store(STORE)


def set_card_file_id(deck_key: str, num: str, file_id: str):
    STORE["cards"].setdefault(deck_key, {})
    STORE["cards"][deck_key][num] = file_id
    save_store(STORE)


def count_cards(deck_key: str) -> int:
    # считаем сколько file_id записано
    return len(STORE.get("cards", {}).get(deck_key, {}))


def total_cards_for_deck(deck_key: str) -> int:
    # у тебя 30 карт; можно оставить 30 даже если не все записаны — тогда будет показывать заглушку
    return 30


HELP_TEXT = (
    "📌 *Как научить бота картинкам (file_id)*\n\n"
    "Отправь боту фото (как обычное фото) и подпиши в подписи:\n\n"
    "— Рубашка для колоды:\n"
    "`BACK state`  или  `BACK release`  или  `BACK resource`\n\n"
    "— Карта:\n"
    "`CARD state 01`\n"
    "`CARD state 02`\n"
    "...\n"
    "`CARD release 01`\n"
    "и т.д.\n\n"
    "Команды:\n"
    "/start — начать\n"
    "/help — эта инструкция\n"
    "/status — сколько карт сохранено\n"
    "/export — показать сохранённые file_id\n"
)


async def main():
    bot = Bot(os.environ[TOKEN_ENV])
    dp = Dispatcher()

    @dp.message(CommandStart())
    async def start(m: Message):
        st = get_player(m.from_user.id)
        st.mode = None
        st.deck = None
        st.page = 0
        await m.answer(
            "✨ *BALANCE WITHIN*\n\nВыбери режим:",
            reply_markup=kb_mode(),
            parse_mode="Markdown",
        )

    @dp.message(Command("help"))
    async def help_cmd(m: Message):
        await m.answer(HELP_TEXT, parse_mode="Markdown")

    @dp.message(Command("status"))
    async def status_cmd(m: Message):
        lines = ["📊 Статус file_id:"]
        for dk in DECKS.keys():
            b = "✅" if get_back_file_id(dk) else "❌"
            lines.append(f"- {DECKS[dk]['title']}: рубашка {b}, карт сохранено: {count_cards(dk)}/30")
        await m.answer("\n".join(lines))

    @dp.message(Command("export"))
    async def export_cmd(m: Message):
        # осторожно: будет длинно, но это удобно скопировать
        await m.answer("```json\n" + json.dumps(STORE, ensure_ascii=False, indent=2) + "\n```", parse_mode="Markdown")

    # Принимаем фото и сохраняем file_id по подписи
    @dp.message(F.photo)
    async def handle_photo(m: Message):
        caption = (m.caption or "").strip()
        if not caption:
            await m.answer("Я получила фото ✅\n\nДобавь подпись (caption), чтобы я поняла, куда сохранить.\nНапиши /help")
            return

        # Берём самое большое фото
        file_id = m.photo[-1].file_id

        parts = caption.split()
        # ожидаем: BACK state
        # или: CARD state 01
        if len(parts) >= 2 and parts[0].upper() == "BACK":
            dk = parts[1].lower()
            if dk not in DECKS:
                await m.answer("❌ Не понимаю колоду. Используй: state / release / resource\nНапиши /help")
                return
            set_back_file_id(dk, file_id)
            await m.answer(f"✅ Сохранила рубашку для {DECKS[dk]['title']}")
            return

        if len(parts) >= 3 and parts[0].upper() == "CARD":
            dk = parts[1].lower()
            num = parts[2]
            if dk not in DECKS:
                await m.answer("❌ Не понимаю колоду. Используй: state / release / resource\nНапиши /help")
                return
            if len(num) == 1:
                num = f"0{num}"
            if not num.isdigit() or not (1 <= int(num) <= 30):
                await m.answer("❌ Номер карты должен быть 01..30\nНапиши /help")
                return
            set_card_file_id(dk, num, file_id)
            await m.answer(f"✅ Сохранила карту {DECKS[dk]['title']} {num}")
            return

        await m.answer("❌ Не поняла подпись.\nНапиши /help (там примеры подписи).")

    @dp.callback_query(F.data == "go:mode")
    async def go_mode(q: CallbackQuery):
        await q.answer()
        st = get_player(q.from_user.id)
        st.mode = None
        st.deck = None
        st.page = 0
        await q.message.answer("Выбери режим:", reply_markup=kb_mode())

    @dp.callback_query(F.data.startswith("mode:"))
    async def set_mode(q: CallbackQuery):
        await q.answer()
        st = get_player(q.from_user.id)
        st.mode = q.data.split(":")[1]
        await q.message.answer("Выбери колоду:", reply_markup=kb_decks())

    @dp.callback_query(F.data == "go:decks")
    async def go_decks(q: CallbackQuery):
        await q.answer()
        await q.message.answer("Выбери колоду:", reply_markup=kb_decks())

    @dp.callback_query(F.data.startswith("deck:"))
    async def show_deck(q: CallbackQuery):
        await q.answer()
        deck_key = q.data.split(":")[1]
        st = get_player(q.from_user.id)
        st.deck = deck_key
        st.page = 0

        back_id = get_back_file_id(deck_key)
        total = total_cards_for_deck(deck_key)

        if not back_id:
            await q.message.answer(
                f"❌ Для колоды *{DECKS[deck_key]['title']}* ещё не сохранена рубашка.\n"
                f"Отправь фото с подписью: `BACK {deck_key}`",
                parse_mode="Markdown",
            )
            return

        await q.message.answer_photo(
            photo=back_id,
            caption=f"{DECKS[deck_key]['title']}\nВыбери карту (можно листать)",
            reply_markup=kb_cards(deck_key, st.page, total),
        )

    @dp.callback_query(F.data.startswith("page:"))
    async def page(q: CallbackQuery):
        await q.answer()
        _, deck_key, page_str = q.data.split(":")
        st = get_player(q.from_user.id)
        st.page = int(page_str)

        total = total_cards_for_deck(deck_key)
        # просто обновляем кнопки
        await q.message.edit_reply_markup(reply_markup=kb_cards(deck_key, st.page, total))

    @dp.callback_query(F.data.startswith("pick:"))
    async def pick(q: CallbackQuery):
        await q.answer()
        _, deck_key, idx_str, page_str = q.data.split(":")
        idx = int(idx_str)
        page = int(page_str)
        num = card_num_from_index(idx)

        await q.message.answer(
            "Почувствуй, готова ли ты открыть эту карту.\n\n"
            "Если отклика нет — вернись и выбери другую.",
            reply_markup=kb_confirm(deck_key, idx, page),
        )

    @dp.callback_query(F.data.startswith("open:"))
    async def open_card(q: CallbackQuery):
        await q.answer()
        _, deck_key, idx_str, page_str = q.data.split(":")
        idx = int(idx_str)
        num = card_num_from_index(idx)

        card_id = get_card_file_id(deck_key, num)
        if not card_id:
            await q.message.answer(
                f"❌ Карта {DECKS[deck_key]['title']} {num} ещё не сохранена.\n"
                f"Отправь фото с подписью: `CARD {deck_key} {num}`",
                parse_mode="Markdown",
            )
            return

        await q.message.answer_photo(photo=card_id, reply_markup=kb_after_open(deck_key))

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
