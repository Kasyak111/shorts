"""
Telegram Sender Utility.
Sends rendered vertical clips directly to your Telegram chat or channel
along with ready-to-copy titles, descriptions, and hashtags for 1-click mobile posting.
"""

import os
import sys
import asyncio
import json
from aiogram import Bot
from aiogram.types import FSInputFile

async def send_clip_to_telegram(
    video_path: str,
    caption: str,
    bot_token: str,
    chat_id: str,
):
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Файл видео не найден: {video_path}")

    bot = Bot(token=bot_token)
    try:
        video_file = FSInputFile(video_path)
        # Telegram captions max limit: 1024 characters
        safe_caption = caption[:1020]
        print(f"✈️ Отправка '{os.path.basename(video_path)}' в Telegram ({chat_id})...")
        await bot.send_video(
            chat_id=chat_id,
            video=video_file,
            caption=safe_caption,
            supports_streaming=True
        )
        print("✅ Видео успешно доставлено в Telegram!")
    finally:
        await bot.session.close()

def send_clip_sync(video_path: str, caption: str, bot_token: str, chat_id: str):
    asyncio.run(send_clip_to_telegram(video_path, caption, bot_token, chat_id))

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Использование: python telegram_sender.py <видео.mp4> <текст_описания>")
        sys.exit(1)

    with open("config.json", "r", encoding="utf-8") as f:
        cfg = json.load(f)

    tg_cfg = cfg.get("telegram", {})
    token = tg_cfg.get("bot_token")
    cid = tg_cfg.get("chat_id")

    if not token or token.startswith("YOUR_"):
        print("❌ Ошибка: укажите bot_token и chat_id в файле config.json")
        sys.exit(1)

    send_clip_sync(sys.argv[1], sys.argv[2], token, cid)
