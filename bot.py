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

# 3 колоды (внутренние ключи)
DECKS = {
    "state": {"title": "🟣 СОСТОЯНИЕ"},
    "release": {"title": "🟡 ОТПУСКАНИЕ"},
    "resource": {"title": "🟢 РЕСУРС"},
}
DECK_ORDER = ["state", "release", "resource"]

PAGE_SIZE = 9
TOTAL_CARDS = 30

STORE_PATH = Path("file_ids.json")


def _safe_load_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _safe_save_json(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


STORE: Dict[str, Any] = _safe_load_json(STORE_PATH)


def ensure_store_shape():
    STORE.setdefault("backs", {})   # backs[deck_key] = file_id
    STORE.setdefault("cards", {})   # cards[deck_key][num] = file_id
    for dk in DECKS.keys():
        STORE["cards"].setdefault(dk, {})


ensure_store_shape()
_safe_save_json(STORE_PATH, STORE)


@dataclass
class PlayerState:
    mode: Optional[str] = None     # "self" / "host"
    deck: Optional[str] = None
    page: int = 0
    picked_idx: Optional[int] = None


PLAYERS: Dict[int, PlayerState] = {}


def get_player(uid: int) -> PlayerState:
    if uid not in PLAYERS:
        PLAYERS[uid] = PlayerState()
    return PLAYERS[uid]


def card_num_from_index(idx: int) -> str:
    return f"{idx + 1:02d}"


def next_deck(current: str) -> Optional[str]:
    try:
        i = DECK_ORDER.index(current)
        if i < len(DECK_ORDER) - 1:
            return DECK_ORDER[i + 1]
    except ValueError:
        return None
    return None


def kb_mode():
    kb = InlineKeyboardBuilder()
    kb.button(text="🧘‍♀️ Для себя", callback_data="mode:self")
    kb.button(text="🤍 С ведущим", callback_data="mode:host")
    kb.adjust(1)
    return kb.as_markup()


def kb_decks():
    kb = InlineKeyboardBuilder()
    kb.button(text=DECKS["state"]["title"], callback_data="deck:state")
    kb.button(text=DECKS["release"]["title"], callback_data="deck:release")
    kb.button(text=DECKS["resource"]["title"], callback_data="deck:resource")
    kb.button(text="🔄 Сменить режим", callback_data="go:mode")
    kb.adjust(1)
    return kb.as_markup()


def kb_cards(deck_key: str, page: int):
    kb = InlineKeyboardBuilder()
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, TOTAL_CARDS)

    for i in range(start, end):
        kb.button(text=f"🂠 {i - start + 1}", callback_data=f"pick:{deck_key}:{i}:{page}")

    nav = InlineKeyboardBuilder()
    if page > 0:
        nav.button(text="◀️", callback_data=f"page:{deck_key}:{page - 1}")
    if end < TOTAL_CARDS:
        nav.button(text="▶️", callback_data=f"page:{deck_key}:{page + 1}")

    kb.adjust(3)
    if nav.buttons:
        kb.row(*nav.buttons)

    kb.button(text="↩️ К колодам", callback_data="go:decks")
    kb.adjust(3, 2, 1)
    return kb.as_markup()


def kb_confirm(deck_key: str, idx: int, page: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Перевернуть", callback_data=f"open:{deck_key}:{idx}:{page}")
    kb.button(text="↩️ Назад", callback_data=f"page:{deck_key}:{page}")
    kb.adjust(1)
    return kb.as_markup()


def kb_after_open(deck_key: str, mode: str):
    kb = InlineKeyboardBuilder()
    nxt = next_deck(deck_key)
    if nxt:
        kb.button(text="➡️ Следующая колода", callback_data=f"deck:{nxt}")
    kb.button(text="🗂️ К колодам", callback_data="go:decks")
    if mode == "host":
        kb.button(text="🧩 Подсказка ведущему", callback_data="host:hint")
    kb.adjust(1)
    return kb.as_markup()


HELP_TEXT = (
    "📌 *Загрузка рубашек и карт без размытия*\n\n"
    "Отправляй изображения боту как **ФАЙЛ (Документ)**, не как Фото.\n\n"
    "*Подпись (caption) к файлу:*\n"
    "— Рубашка колоды:\n"
    "`BACK state` / `BACK release` / `BACK resource`\n\n"
    "— Карта:\n"
    "`CARD state 01`\n"
    "`CARD release 15`\n"
    "`CARD resource 30`\n\n"
    "Команды:\n"
    "/start — начать\n"
    "/status — проверить, что сохранено\n"
    "/reset — очистить всё (если загрузилось размыто)\n"
    "/help — эта инструкция\n"
)


def set_back(deck_key: str, file_id: str):
    STORE["backs"][deck_key] = file_id
    _safe_save_json(STORE_PATH, STORE)


def set_card(deck_key: str, num: str, file_id: str):
    STORE["cards"].setdefault(deck_key, {})
    STORE["cards"][deck_key][num] = file_id
    _safe_save_json(STORE_PATH, STORE)


def get_back(deck_key: str) -> Optional[str]:
    return STORE.get("backs", {}).get(deck_key)


def get_card(deck_key: str, num: str) -> Optional[str]:
    return STORE.get("cards", {}).get(deck_key, {}).get(num)


def count_cards(deck_key: str) -> int:
    return len(STORE.get("cards", {}).get(deck_key, {}))


async def main():
    token = os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not set")

    bot = Bot(token)
    dp = Dispatcher()

    @dp.message(CommandStart())
    async def start(m: Message):
        st = get_player(m.from_user.id)
        st.mode = None
        st.deck = None
        st.page = 0
        st.picked_idx = None
        await m.answer("✨ *BALANCE WITHIN*\n\nВыбери режим:", reply_markup=kb_mode(), parse_mode="Markdown")

    @dp.message(Command("help"))
    async def help_cmd(m: Message):
        await m.answer(HELP_TEXT, parse_mode="Markdown")

    @dp.message(Command("status"))
    async def status_cmd(m: Message):
        lines = ["📊 *Статус сохранённых file_id:*"]
        for dk in DECKS.keys():
            b = "✅" if get_back(dk) else "❌"
            lines.append(f"{DECKS[dk]['title']}: рубашка {b}, карт {count_cards(dk)}/30")
        await m.answer("\n".join(lines), parse_mode="Markdown")

    @dp.message(Command("reset"))
    async def reset_cmd(m: Message):
        STORE.clear()
        ensure_store_shape()
        _safe_save_json(STORE_PATH, STORE)
        await m.answer("✅ Очищено. Можно загружать рубашки/карты заново.")

    # Принимаем изображения как ФАЙЛ (Document) — без сжатия
    @dp.message(F.document)
    async def handle_document(m: Message):
        caption = (m.caption or "").strip()
        if not caption:
            await m.answer("Я получила файл ✅\nДобавь подпись (caption). Напиши /help")
            return

        # Берём file_id документа
        file_id = m.document.file_id
        parts = caption.split()

        # BACK deck
        if len(parts) >= 2 and parts[0].upper() == "BACK":
            dk = parts[1].lower()
            if dk not in DECKS:
                await m.answer("❌ Колода: state / release / resource\nНапиши /help")
                return
            set_back(dk, file_id)
            await m.answer(f"✅ Сохранила рубашку для {DECKS[dk]['title']}")
            return

        # CARD deck NN
        if len(parts) >= 3 and parts[0].upper() == "CARD":
            dk = parts[1].lower()
            num = parts[2]
            if dk not in DECKS:
                await m.answer("❌ Колода: state / release / resource\nНапиши /help")
                return
            if len(num) == 1:
                num = f"0{num}"
            if (not num.isdigit()) or (int(num) < 1 or int(num) > 30):
                await m.answer("❌ Номер карты должен быть 01..30\nНапиши /help")
                return
            set_card(dk, num, file_id)
            await m.answer(f"✅ Сохранила карту {DECKS[dk]['title']} {num}")
            return

        await m.answer("❌ Не поняла подпись.\nНапиши /help (там примеры).")

    @dp.callback_query(F.data == "go:mode")
    async def go_mode(q: CallbackQuery):
        await q.answer()
        st = get_player(q.from_user.id)
        st.mode = None
        st.deck = None
        st.page = 0
        st.picked_idx = None
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
        st.picked_idx = None

        back_id = get_back(deck_key)
        if not back_id:
            await q.message.answer(
                f"❌ Для {DECKS[deck_key]['title']} ещё нет рубашки.\n"
                f"Отправь файл с подписью: `BACK {deck_key}`",
                parse_mode="Markdown",
            )
            return

        await q.message.answer_photo(
            photo=back_id,
            caption=f"{DECKS[deck_key]['title']}\nВыбери карту (можно листать)",
            reply_markup=kb_cards(deck_key, st.page),
        )

    @dp.callback_query(F.data.startswith("page:"))
    async def page(q: CallbackQuery):
        await q.answer()
        _, deck_key, page_str = q.data.split(":")
        st = get_player(q.from_user.id)
        st.page = int(page_str)
        await q.message.edit_reply_markup(reply_markup=kb_cards(deck_key, st.page))

    @dp.callback_query(F.data.startswith("pick:"))
    async def pick(q: CallbackQuery):
        await q.answer()
        _, deck_key, idx_str, page_str = q.data.split(":")
        idx = int(idx_str)
        page = int(page_str)

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

        card_id = get_card(deck_key, num)
        if not card_id:
            await q.message.answer(
                f"❌ Карта {DECKS[deck_key]['title']} {num} ещё не загружена.\n"
                f"Отправь файл с подписью: `CARD {deck_key} {num}`",
                parse_mode="Markdown",
            )
            return

        st = get_player(q.from_user.id)
        await q.message.answer_photo(photo=card_id, reply_markup=kb_after_open(deck_key, st.mode or "self"))

    @dp.callback_query(F.data == "host:hint")
    async def host_hint(q: CallbackQuery):
        await q.answer()
        await q.message.answer(
            "🤍 *Подсказка ведущему*\n\n"
            "— Не интерпретируй карту и не давай советов.\n"
            "— Поддерживай паузы.\n"
            "— Мягкие вопросы: «Что сейчас важно?», «Где это в теле?»\n"
            "— Если участница не хочет отвечать — это нормально.",
            parse_mode="Markdown",
        )

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
