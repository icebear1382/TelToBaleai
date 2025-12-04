import asyncio
import logging
import os
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import Dict, Optional, List

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.tl.types import Message

from bale import Bot  
from bale import Bot, InputFile


from telethon.utils import get_peer_id



# ------------- Config & Globals -------------

load_dotenv()

TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_SESSION = os.getenv("TELEGRAM_SESSION", "tg_session")

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # Telegram user id of admin

BALE_BOT_TOKEN = os.getenv("BALE_BOT_TOKEN", "")

KEYWORDS = [k.strip() for k in os.getenv("KEYWORDS", "").split(",") if k.strip()]
REMOVE_PATTERNS = [p.strip() for p in os.getenv("REMOVE_PATTERNS", "").split(",") if p.strip()]

SEND_DELAY_SECONDS = float(os.getenv("SEND_DELAY_SECONDS", "1.5"))

DB_PATH = os.getenv("DB_PATH", "db.sqlite3")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("tg_bale_bridge")


@dataclass
class ChannelConfig:
    id: int
    tg_chat_id: int
    tg_link: str
    bale_dest: str
    caption: str
    enabled: bool


# cache: chat_id -> ChannelConfig
CHANNELS_BY_CHAT_ID: Dict[int, ChannelConfig] = {}

# simple state for admin conversation
ADMIN_STATE: Dict[str, Optional[str]] = {
    "mode": "idle",
    "channel_id": None,
    "new_tg_link": None,
}


# ------------- DB helpers -------------

def init_db():
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_chat_id INTEGER NOT NULL,
                tg_link TEXT NOT NULL,
                bale_dest TEXT NOT NULL,
                caption TEXT DEFAULT '',
                enabled INTEGER DEFAULT 1
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sent_messages (
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                PRIMARY KEY (chat_id, message_id)
            )
            """
        )
        conn.commit()


def load_channels() -> Dict[int, ChannelConfig]:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, tg_chat_id, tg_link, bale_dest, caption, enabled FROM channels"
        )
        rows = cur.fetchall()

    by_chat: Dict[int, ChannelConfig] = {}
    for row in rows:
        cfg = ChannelConfig(
            id=row[0],
            tg_chat_id=row[1],
            tg_link=row[2],
            bale_dest=row[3],
            caption=row[4] or "",
            enabled=bool(row[5]),
        )
        by_chat[cfg.tg_chat_id] = cfg

    logger.info("Loaded %d channels from DB", len(by_chat))
    return by_chat


def add_channel(tg_chat_id: int, tg_link: str, bale_dest: str) -> int:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO channels (tg_chat_id, tg_link, bale_dest) VALUES (?, ?, ?)",
            (tg_chat_id, tg_link, bale_dest),
        )
        conn.commit()
        return cur.lastrowid


def update_channel_caption(channel_id: int, caption: str):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE channels SET caption = ? WHERE id = ?",
            (caption, channel_id),
        )
        conn.commit()


def update_channel_bale_dest(channel_id: int, bale_dest: str):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE channels SET bale_dest = ? WHERE id = ?",
            (bale_dest, channel_id),
        )
        conn.commit()


def delete_channel(channel_id: int):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
        conn.commit()


def is_duplicate(chat_id: int, message_id: int) -> bool:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM sent_messages WHERE chat_id = ? AND message_id = ?",
            (chat_id, message_id),
        )
        return cur.fetchone() is not None


def mark_sent(chat_id: int, message_id: int):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO sent_messages (chat_id, message_id) VALUES (?, ?)",
            (chat_id, message_id),
        )
        conn.commit()


# ------------- Text helpers -------------

def filter_by_keywords(text: str, keywords: List[str]) -> bool:
    if not keywords:
        return True
    low = text.lower()
    return any(k.lower() in low for k in keywords)


def clean_text(text: str) -> str:
    if not text:
        return text

    # remove @usernames
    text = re.sub(r"@\w+", "", text)
    # remove t.me links
    text = re.sub(r"https?://t\.me/\S+", "", text)

    for pattern in REMOVE_PATTERNS:
        text = text.replace(pattern, "")

    # trim extra spaces/newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)

    return text.strip()


# ------------- Bale sender -------------

class BaleSender:
    def __init__(self, token: str):
        self.client = Bot(token=token)

    async def send_text(self, chat_id: str, text: str):
        async with self.client as bot:
            await bot.send_message(chat_id=chat_id, text=text)

    async def send_photo(self, chat_id: str, photo_bytes: bytes, caption: str | None = None):
        input_file = InputFile(photo_bytes, file_name="photo.jpg")
        async with self.client as bot:
            await bot.send_photo(chat_id=chat_id, photo=input_file, caption=caption)

    async def send_video(self, chat_id: str, video_bytes: bytes, caption: str | None = None):
        input_file = InputFile(video_bytes, file_name="video.mp4")
        async with self.client as bot:
            await bot.send_video(chat_id=chat_id, video=input_file, caption=caption)


# ------------- Admin panel -------------

async def send_admin_help(event):
    text = (
        "پنل مدیریت:\n"
        "/channels - لیست کانال‌ها\n"
        "/addchannel - اضافه کردن کانال جدید\n"
        "/manage <id> - مدیریت یک کانال خاص\n"
        "/cancel - لغو عملیات جاری\n"
    )
    await event.reply(text)


async def handle_admin_command(event, client: TelegramClient):
    global CHANNELS_BY_CHAT_ID, ADMIN_STATE

    sender_id = event.sender_id
    if sender_id != ADMIN_ID:
        return

    text = (event.raw_text or "").strip()

    # commands with slash reset state (mostly)
    if text.startswith("/start") or text.startswith("/panel"):
        ADMIN_STATE = {"mode": "idle", "channel_id": None, "new_tg_link": None}
        await send_admin_help(event)
        return

    if text.startswith("/cancel"):
        ADMIN_STATE = {"mode": "idle", "channel_id": None, "new_tg_link": None}
        await event.reply("عملیات لغو شد.")
        return

    if text.startswith("/channels"):
        if not CHANNELS_BY_CHAT_ID:
            await event.reply("هیچ کانالی ثبت نشده.")
            return

        lines = ["لیست کانال‌ها:"]
        # sort by id
        by_id = sorted(CHANNELS_BY_CHAT_ID.values(), key=lambda c: c.id)
        for cfg in by_id:
            enabled = "✅" if cfg.enabled else "❌"
            caption_flag = "✔" if cfg.caption else "✖"
            lines.append(
                f"{cfg.id}) {cfg.tg_link} → {cfg.bale_dest} [{enabled}] کپشن: {caption_flag}"
            )
        lines.append("\nبرای مدیریت هر کانال از دستور زیر استفاده کن:\n/manage <id>")
        await event.reply("\n".join(lines))
        ADMIN_STATE["mode"] = "idle"
        return

    if text.startswith("/addchannel"):
        ADMIN_STATE = {"mode": "adding_tg_link", "channel_id": None, "new_tg_link": None}
        await event.reply(
            "آیدی یا لینک کانال تلگرام را بفرست (مثلاً @mychannel یا https://t.me/mychannel)."
        )
        return

    if text.startswith("/manage"):
        parts = text.split()
        if len(parts) != 2 or not parts[1].isdigit():
            await event.reply("فرمت دستور اشتباه است. مثال:\n/manage 1")
            return
        chan_id = int(parts[1])

        # find config by id
        target: Optional[ChannelConfig] = None
        for cfg in CHANNELS_BY_CHAT_ID.values():
            if cfg.id == chan_id:
                target = cfg
                break

        if not target:
            await event.reply("کانال با این شناسه پیدا نشد.")
            return

        ADMIN_STATE = {"mode": "manage_wait_choice", "channel_id": str(chan_id), "new_tg_link": None}
        await event.reply(
            f"مدیریت کانال {chan_id} ({target.tg_link}):\n"
            "1- تنظیم/تغییر کپشن همیشگی\n"
            "2- تنظیم/تغییر آیدی یا chat_id مقصد بله\n"
            "3- حذف کانال\n"
            "عدد گزینه مورد نظر را بفرست."
        )
        return

    # handle conversational states
    mode = ADMIN_STATE.get("mode")

    if mode == "adding_tg_link":
        tg_link = text
        ADMIN_STATE["new_tg_link"] = tg_link
        ADMIN_STATE["mode"] = "adding_bale_dest"
        await event.reply(
            "آیدی یا chat_id مقصد در بله را بفرست (مثلاً @my_bale_channel یا عدد chat_id)."
        )
        return

    if mode == "adding_bale_dest":
        tg_link = ADMIN_STATE.get("new_tg_link")
        bale_dest = text

        if not tg_link:
            await event.reply("خطا در ثبت لینک کانال. دوباره /addchannel بزن.")
            ADMIN_STATE = {"mode": "idle", "channel_id": None, "new_tg_link": None}
            return

        try:
            entity = await client.get_entity(tg_link)
            tg_chat_id = get_peer_id(entity)
        except Exception as e:
            logger.exception("Failed to resolve channel link: %s", e)
            await event.reply("نتوانستم کانال را پیدا کنم. آیدی/لینک را چک کن.")
            ADMIN_STATE = {"mode": "idle", "channel_id": None, "new_tg_link": None}
            return

        chan_id = add_channel(tg_chat_id, tg_link, bale_dest)
        CHANNELS_BY_CHAT_ID = load_channels()
        ADMIN_STATE = {"mode": "idle", "channel_id": None, "new_tg_link": None}
        await event.reply(f"کانال جدید با شناسه {chan_id} اضافه شد.")
        return

    if mode == "manage_wait_choice":
        chan_id_str = ADMIN_STATE.get("channel_id")
        if not chan_id_str or not chan_id_str.isdigit():
            await event.reply("شناسه کانال نامعتبر است. دوباره /manage بزن.")
            ADMIN_STATE = {"mode": "idle", "channel_id": None, "new_tg_link": None}
            return

        chan_id = int(chan_id_str)
        choice = text.strip()
        if choice == "1":
            ADMIN_STATE["mode"] = "set_caption"
            ADMIN_STATE["channel_id"] = str(chan_id)
            await event.reply("متن کپشن همیشگی را بفرست (برای خالی کردن کپشن، یک - بفرست).")
            return
        elif choice == "2":
            ADMIN_STATE["mode"] = "set_bale_dest"
            ADMIN_STATE["channel_id"] = str(chan_id)
            await event.reply("آیدی/شناسه جدید مقصد بله را بفرست.")
            return
        elif choice == "3":
            delete_channel(chan_id)
            CHANNELS_BY_CHAT_ID = load_channels()
            ADMIN_STATE = {"mode": "idle", "channel_id": None, "new_tg_link": None}
            await event.reply("کانال حذف شد.")
            return
        else:
            await event.reply("گزینه نامعتبر. فقط 1 یا 2 یا 3.")
            return

    if mode == "set_caption":
        chan_id_str = ADMIN_STATE.get("channel_id")
        if not chan_id_str or not chan_id_str.isdigit():
            await event.reply("شناسه کانال نامعتبر است.")
            ADMIN_STATE = {"mode": "idle", "channel_id": None, "new_tg_link": None}
            return

        chan_id = int(chan_id_str)
        caption = "" if text.strip() == "-" else text
        update_channel_caption(chan_id, caption)
        CHANNELS_BY_CHAT_ID = load_channels()
        ADMIN_STATE = {"mode": "idle", "channel_id": None, "new_tg_link": None}
        await event.reply("کپشن ذخیره شد.")
        return

    if mode == "set_bale_dest":
        chan_id_str = ADMIN_STATE.get("channel_id")
        if not chan_id_str or not chan_id_str.isdigit():
            await event.reply("شناسه کانال نامعتبر است.")
            ADMIN_STATE = {"mode": "idle", "channel_id": None, "new_tg_link": None}
            return
        chan_id = int(chan_id_str)
        update_channel_bale_dest(chan_id, text.strip())
        CHANNELS_BY_CHAT_ID = load_channels()
        ADMIN_STATE = {"mode": "idle", "channel_id": None, "new_tg_link": None}
        await event.reply("آیدی مقصد بله به‌روزرسانی شد.")
        return

    # if nothing matched, show help
    await send_admin_help(event)


# ------------- Message bridge -------------

async def handle_channel_message(event, bale_sender: BaleSender):
    global CHANNELS_BY_CHAT_ID

    msg: Message = event.message
    chat_id = get_peer_id(msg.peer_id)

    cfg = CHANNELS_BY_CHAT_ID.get(chat_id)
    if not cfg or not cfg.enabled:
        logger.info(f"handle_channel_message: chat_id={chat_id}, known={list(CHANNELS_BY_CHAT_ID.keys())}")
        return

    if is_duplicate(chat_id, msg.id):
        logger.info("Duplicate message %s in chat %s; skipping", msg.id, chat_id)
        return

    text = msg.message or ""

    if not text and not msg.media:
        logger.info("Message %s has no text/media; skipping", msg.id)
        return

    if text and not filter_by_keywords(text, KEYWORDS):
        logger.info("Message %s filtered by keywords", msg.id)
        return

    text = clean_text(text)

    if cfg.caption:
        text = f"{text}\n\n{cfg.caption}" if text else cfg.caption

    caption = text if text else None

    try:

        if msg.photo:
            media_bytes = await msg.download_media(bytes)
            await bale_sender.send_photo(cfg.bale_dest, media_bytes, caption=caption)
            logger.info("Forwarded PHOTO %s from %s to Bale %s", msg.id, cfg.tg_link, cfg.bale_dest)
            mark_sent(chat_id, msg.id)
            await asyncio.sleep(SEND_DELAY_SECONDS)
            return


        if msg.video:
            media_bytes = await msg.download_media(bytes)
            await bale_sender.send_video(cfg.bale_dest, media_bytes, caption=caption)
            logger.info("Forwarded VIDEO %s from %s to Bale %s", msg.id, cfg.tg_link, cfg.bale_dest)
            mark_sent(chat_id, msg.id)
            await asyncio.sleep(SEND_DELAY_SECONDS)
            return


        if caption:
            await bale_sender.send_text(cfg.bale_dest, caption)
            logger.info("Forwarded TEXT %s from %s to Bale %s", msg.id, cfg.tg_link, cfg.bale_dest)
            mark_sent(chat_id, msg.id)
            await asyncio.sleep(SEND_DELAY_SECONDS)

    except Exception as e:
        logger.exception("Failed to send message to Bale: %s", e)



async def main():
    global CHANNELS_BY_CHAT_ID

    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        raise RuntimeError("TELEGRAM_API_ID/HASH not set in environment variables.")
    if not ADMIN_ID:
        raise RuntimeError("ADMIN_ID not set in environment variables.")
    if not BALE_BOT_TOKEN:
        raise RuntimeError("BALE_BOT_TOKEN not set in environment variables.")

    init_db()
    CHANNELS_BY_CHAT_ID = load_channels()

    from telethon.network.connection import ConnectionTcpAbridged

    proxy = ("socks5", "127.0.0.1", 10808)

    tg_client = TelegramClient(TELEGRAM_SESSION, TELEGRAM_API_ID, TELEGRAM_API_HASH)
    bale_sender = BaleSender(BALE_BOT_TOKEN)

    @tg_client.on(events.NewMessage)
    async def all_messages_handler(event):
        # admin panel in private chat
        if event.is_private and event.sender_id == ADMIN_ID:
            await handle_admin_command(event, tg_client)
        else:
            await handle_channel_message(event, bale_sender)

    async with tg_client:
        logger.info("Bot is running. Admin can use /panel in private chat.")
        await tg_client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
