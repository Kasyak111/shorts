"""
Telegram Remote Control & Delivery Bot (aiogram 3).
Allows managing the movie shorts automation pipeline directly from your smartphone:
- Search and rip trending competitor clips with 1 click
- Send a YouTube/Shorts URL to automatically process into 3 platforms
- Delivers ready-to-post vertical videos with FunPay/PlayerOk banners and copy-paste descriptions
- Tracks published clips with "Выпустил" button so they are never searched or suggested again
"""

import os
import sys
import json
import asyncio
import time
import re
from typing import Dict, Any, Optional, List
from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.filters import Command
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo,
    FSInputFile,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from smart_autopilot import SmartAutopilot
from clip_manager import ClipManager
from history_manager import HistoryManager
from subtitle_styler import SubtitleStyler
from grammar_corrector import save_user_rule
from web_server import MovieEditorWebServer
from tunnel_manager import TunnelManager

CONFIG_PATH = "config.json"

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def get_allowed_users() -> List[int]:
    cfg = load_config()
    allowed = cfg.get("telegram", {}).get("allowed_user_ids", [])
    if isinstance(allowed, (int, str)):
        allowed = [allowed]
    return [int(uid) for uid in allowed if str(uid).isdigit()]

def save_allowed_user(user_id: int):
    cfg = load_config()
    tg = cfg.setdefault("telegram", {})
    allowed = tg.get("allowed_user_ids", [])
    if isinstance(allowed, (int, str)):
        allowed = [allowed]
    allowed_ints = [int(u) for u in allowed if str(u).isdigit()]
    if user_id not in allowed_ints:
        allowed_ints.append(user_id)
        tg["allowed_user_ids"] = allowed_ints
        tg["chat_id"] = str(user_id)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)

config = load_config()
tg_cfg = config.get("telegram", {})
BOT_TOKEN = tg_cfg.get("bot_token")

# Initialize persistent published history tracker
history = HistoryManager()

# In-memory store for pending clip metadata to associate with buttons
pending_clips: Dict[str, Dict[str, Any]] = {}
active_user_edits: Dict[int, Dict[str, Any]] = {}

# Global web server and tunnel references
web_server_instance: Optional[MovieEditorWebServer] = None
tunnel_instance: Optional[TunnelManager] = None

# Interactive keyboard
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="🚀 Найти и нарезать вирусный ролик"),
        ],
        [
            KeyboardButton(text="📱 Видео-Редактор (Mini App)"),
            KeyboardButton(text="📁 Последние готовые ролики"),
        ],
        [
            KeyboardButton(text="📊 Архив выпущенных"),
            KeyboardButton(text="ℹ️ Помощь и статус"),
        ],
    ],
    resize_keyboard=True,
)

def ensure_video_under_telegram_limit(vid_path: str, max_mb: float = 48.0) -> str:
    """Ensures video is strictly under Telegram's 50 MB limit, compressing if necessary."""
    if not vid_path or not os.path.exists(vid_path):
        return vid_path
    size_mb = os.path.getsize(vid_path) / (1024 * 1024)
    if size_mb <= max_mb:
        return vid_path

    # Video exceeds 48 MB - compress to safe size ~30 MB
    print(f"⚠️ Видео {os.path.basename(vid_path)} весит {size_mb:.1f} MB (> 48 MB). Сжимаю для Telegram...", flush=True)
    out_dir = os.path.dirname(vid_path)
    base_name = os.path.basename(vid_path)
    comp_path = os.path.join(out_dir, f"safe_{base_name}")
    
    cmd = [
        "ffmpeg", "-y", "-i", vid_path,
        "-c:v", "libx264", "-preset", "ultrafast",
        "-crf", "24",
        "-maxrate", "4000k", "-bufsize", "8000k",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        comp_path
    ]
    try:
        import subprocess
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if os.path.exists(comp_path) and os.path.getsize(comp_path) > 0:
            try:
                os.replace(comp_path, vid_path)
                return vid_path
            except Exception:
                return comp_path
    except Exception as e:
        print(f"Ошибка компрессии: {e}", flush=True)
    return vid_path

def make_published_kb(source_id: str, is_pub: bool = False, clip_id: str = None) -> InlineKeyboardMarkup:
    """Generates inline button to mark or unmark a video as published, open Mini App, or correct subtitles."""
    if not is_pub:
        cid = clip_id or (pending_clips.get(source_id, {}).get("clip_id")) or f"auto_{source_id}"
        
        # Determine WebApp or Browser URL
        if web_server_instance and web_server_instance.public_url:
            tma_url = f"{web_server_instance.public_url}/webapp?clip={cid}"
            tma_btn = InlineKeyboardButton(
                text="📱 Видео-Редактор (Mini App)",
                web_app=WebAppInfo(url=tma_url)
            )
        else:
            tma_url = f"http://localhost:8080/webapp?clip={cid}"
            tma_btn = InlineKeyboardButton(
                text="🌐 Видео-Редактор (Web)",
                url=tma_url
            )

        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Выпустил (больше не показывать)",
                        callback_data=f"pub:{source_id}"
                    )
                ],
                [
                    tma_btn
                ],
                [
                    InlineKeyboardButton(
                        text="✏️ Текстом в чате",
                        callback_data=f"editsubs:{source_id}"
                    ),
                    InlineKeyboardButton(
                        text="🔤 Заменить слово",
                        callback_data=f"replaceword:{source_id}"
                    )
                ]
            ]
        )
    else:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🟢 ВЫПУЩЕНО В СЕТЬ (в архиве)",
                        callback_data=f"info:{source_id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="↩️ Вернуть в поиск (отменить)",
                        callback_data=f"unpub:{source_id}"
                    )
                ]
            ]
        )

class AccessControlMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        user_id = user.id
        allowed = get_allowed_users()

        if user_id not in allowed:
            if isinstance(event, types.CallbackQuery):
                await event.answer("⛔ Доступ ограничен. Этот бот является персональным.", show_alert=True)
            elif isinstance(event, types.Message):
                await event.answer(
                    "⛔ **Доступ запрещен.**\n\n"
                    "Этот бот является персональным и настроен исключительно для своего владельца.",
                    parse_mode="Markdown"
                )
            return

        return await handler(event, data)

dp = Dispatcher()
dp.message.outer_middleware(AccessControlMiddleware())
dp.callback_query.outer_middleware(AccessControlMiddleware())

@dp.message(Command("my_id", "owner", "id"))
async def cmd_my_id(message: types.Message):
    user_id = message.from_user.id
    allowed = get_allowed_users()
    status = "👑 Владелец (доступ открыт)" if user_id in allowed else "❌ Доступ закрыт"
    await message.answer(
        f"👤 **Информация о доступе:**\n\n"
        f"• Ваш ID: `{user_id}`\n"
        f"• Статус: {status}\n"
        f"• Список разрешенных ID: `{allowed}`",
        parse_mode="Markdown"
    )

@dp.message(Command("add_user", "allow"))
async def cmd_add_user(message: types.Message):
    parts = message.text.strip().split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Использование: `/add_user <telegram_id>`", parse_mode="Markdown")
        return
    new_id = int(parts[1])
    save_allowed_user(new_id)
    await message.answer(f"✅ Пользователь с ID `{new_id}` добавлен в список разрешенных!", parse_mode="Markdown")

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    welcome_text = (
        "🎬 **Movie Shorts & Reels Automation Bot**\n\n"
        "Привет! Этот бот позволяет управлять нарезкой фильмов прямо со смартфона.\n\n"
        "✨ **Возможности:**\n"
        "1. 🚀 **«Найти и нарезать вирусный ролик»** — автопоиск вирусных моментов кино, нарезка с динамическими титрами и безопасными cinema-описаниями.\n"
        "2. 🔗 **Отправь ссылку на YouTube/Shorts** — бот скачает и подготовит ролик под все 3 платформы.\n"
        "3. ✅ **Кнопка «Выпустил»** — нажми после публикации в соцсетях: бот навсегда запомнит ролик и больше никогда не будет искать его или предлагать повторно!\n"
        "4. 📊 **«Архив выпущенных»** — просмотр всех опубликованных фрагментов с возможностью управления.\n"
    )
    await message.answer(welcome_text, reply_markup=main_kb, parse_mode="Markdown")

@dp.message(F.text == "📱 Видео-Редактор (Mini App)")
@dp.message(Command("app", "editor", "webapp"))
async def action_open_mini_app(message: types.Message):
    # Find latest clip
    cid = None
    if pending_clips:
        last_src = list(pending_clips.keys())[-1]
        cid = pending_clips[last_src].get("clip_id") or f"auto_{last_src}"
    if not cid:
        mgr = ClipManager()
        if os.path.exists(mgr.output_base):
            for entry in sorted(os.scandir(mgr.output_base), key=lambda e: e.stat().st_mtime, reverse=True):
                if entry.is_dir() and entry.name.startswith("auto_"):
                    cid = entry.name
                    break

    if web_server_instance and web_server_instance.public_url:
        url = f"{web_server_instance.public_url}/webapp" + (f"?clip={cid}" if cid else "")
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📱 Открыть видео-редактор", web_app=WebAppInfo(url=url))
        ]])
    else:
        url = f"http://localhost:8080/webapp" + (f"?clip={cid}" if cid else "")
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🌐 Открыть видео-редактор", url=url)
        ]])

    await message.answer(
        "📱 **Telegram Mini App — Интерактивный Видео-Редактор:**\n\n"
        "• 🎬 Вертикальный 9:16 видеоплеер с оверлеем субтитров\n"
        "• 💬 Нажмите на реплику, чтобы перемотать видео к моменту речи\n"
        "• ✏️ Мгновенное исправление текста и опечаток прямо на экране\n"
        "• ⏱️ Точная микро-подгонка тайминга кнопками `[-0.1s]` / `[+0.1s]`\n"
        "• ⚡ Быстрый рендер ролика прямо в чат!\n\n"
        "Нажмите кнопку ниже, чтобы открыть:",
        reply_markup=kb,
        parse_mode="Markdown"
    )

@dp.message(F.text == "ℹ️ Помощь и статус")
async def cmd_help(message: types.Message):
    pub_count = history.get_published_count()
    status_text = (
        "📊 **Текущий статус системы:**\n\n"
        "✅ Движок: FFmpeg + Pillow + yt-dlp + Faster-Whisper + Pymorphy3\n"
        "🎬 Баннеры: Органические кино-плашки (без сторонней рекламы и ссылок)\n"
        "💬 Субтитры: Белый Impact + черный контур + Bounce Pop-In + автокоррекция падежей\n"
        f"📦 Опубликовано и скрыто из поиска: **{pub_count}** роликов\n\n"
        "Команды:\n"
        "• `/set_key <ключ>` — привязать бесплатный Google Gemini API (для студийного качества субтитров)\n"
        "• `/archive` — посмотреть архив выпущенных видео\n"
        "• `/spy <запрос>` — поиск по конкретному запросу\n"
        "• Отправь любую ссылку на YouTube / Shorts прямо в чат!"
    )
    await message.answer(status_text, reply_markup=main_kb, parse_mode="Markdown")

@dp.message(Command("set_key"))
async def cmd_set_key(message: types.Message):
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "🔑 **Как привязать бесплатный ключ Google Gemini:**\n\n"
            "1. Перейдите на [aistudio.google.com/apikey](https://aistudio.google.com/apikey) и нажмите **Create API Key** (бесплатно, без карт).\n"
            "2. Отправьте боту команду:\n"
            "`/set_key ВАШ_КЛЮЧ`\n"
            "*(или просто отправьте скопированный ключ прямо в этот чат)*.\n\n"
            "✨ **Что даст ключ:**\n"
            "• Исправление имен («АХИ ЛЕЗ» ➔ «АХИЛЛЕС»)\n"
            "• Исправление падежей («К ЖЁНОМ» ➔ «К ЖЁНАМ»)\n"
            "• Полное удаление войсоверов блогеров («С вами был Игорь Негода...»)\n"
            "• Идеальная кино-пунктуация без висячих предлогов.",
            parse_mode="Markdown"
        )
        return
    new_key = parts[1].strip()
    from llm_corrector import LLMSubtitleCorrector
    llm = LLMSubtitleCorrector(config_path="config.json")
    if llm.set_api_key(new_key):
        await message.answer("✅ **API-ключ Google Gemini успешно сохранен!**\nТеперь все субтитры полируются интеллектуальной языковой моделью с контекстом кино.", reply_markup=main_kb)
    else:
        await message.answer("❌ Ошибка сохранения ключа. Проверьте правильность.")

@dp.message(F.text.startswith("AIzaSy"))
async def cmd_auto_key(message: types.Message):
    new_key = message.text.strip()
    from llm_corrector import LLMSubtitleCorrector
    llm = LLMSubtitleCorrector(config_path="config.json")
    if llm.set_api_key(new_key):
        await message.answer("✅ **Ключ Google Gemini автоматически распознан и сохранен!**\nСтудийный редактор субтитров активирован на 100%.", reply_markup=main_kb)
    else:
        await message.answer("❌ Не удалось сохранить ключ.")

@dp.message(F.text == "📊 Архив выпущенных")
@dp.message(Command("archive"))
async def cmd_archive(message: types.Message):
    items = history.get_published_list()
    count = len(items)
    if count == 0:
        await message.answer(
            "📊 **Архив опубликованных роликов пуст.**\n\n"
            "После того как бот пришлет готовые видео, нажмите кнопку:\n"
            "«✅ **Выпустил (больше не показывать)**».\n\n"
            "Тогда этот ролик больше никогда не будет искаться или нарезаться.",
            reply_markup=main_kb,
            parse_mode="Markdown"
        )
        return

    text = f"📊 **Архив опубликованных роликов ({count} шт.):**\n\n"
    recent_items = items[-8:]
    inline_rows = []
    for i, it in enumerate(reversed(recent_items), 1):
        t = it.get('title', 'Без названия')
        date = it.get('published_at', '')
        vid = it.get('id', '')
        text += f"{i}. 🎬 **{t[:42]}**\n   📅 {date}\n"
        btn_text = f"↩️ Вернуть: {t[:22]}..."
        inline_rows.append([InlineKeyboardButton(text=btn_text, callback_data=f"unpub:{vid}")])

    if count > 8:
        text += f"\n_...и ещё {count - 8} роликов в архиве._\n"

    text += "\n💡 *Все эти ролики навсегда исключены из поиска и рекомендаций автопилота.*"
    kb = InlineKeyboardMarkup(inline_keyboard=inline_rows) if inline_rows else None
    await message.answer(text, reply_markup=kb, parse_mode="Markdown")

@dp.message(F.text == "📁 Последние готовые ролики")
async def cmd_recent(message: types.Message):
    out_dir = "output"
    if not os.path.exists(out_dir):
        await message.answer("📁 Папка output пуста. Нарежьте первый ролик кнопкой ниже!", reply_markup=main_kb)
        return

    mp4_files = []
    for root, _, files in os.walk(out_dir):
        for f in files:
            if f.endswith(".mp4"):
                full_p = os.path.join(root, f)
                mp4_files.append((os.path.getmtime(full_p), full_p))

    if not mp4_files:
        await message.answer("📁 Пока нет готовых видео. Нажмите «🚀 Найти и нарезать вирусный ролик»!", reply_markup=main_kb)
        return

    mp4_files.sort(reverse=True)
    recent = mp4_files[:3]
    await message.answer(f"📁 Найдено последних роликов: {len(recent)}. Отправляю свежий комплект...")
    for _, vid_path in recent:
        try:
            safe_vid = ensure_video_under_telegram_limit(vid_path)
            await message.answer_video(
                video=FSInputFile(safe_vid),
                caption=f"🎬 Файл: {os.path.basename(safe_vid)}"
            )
        except Exception as e:
            await message.answer(f"Не удалось отправить {os.path.basename(vid_path)}: {e}")

@dp.message(F.text == "🚀 Найти и нарезать вирусный ролик")
async def action_auto_spy(message: types.Message):
    status_msg = await message.answer("🔎 Ищу вирусные моменты фильмов в трендах... Сверяю с архивом и отсеиваю видео без слов. Подожди 1-2 минуты.")

    loop = asyncio.get_event_loop()
    autopilot = SmartAutopilot()

    try:
        results = await loop.run_in_executor(None, lambda: autopilot.run(count=1, min_views=0))
        if not results:
            await status_msg.edit_text("⚠️ Не удалось найти свежие ролики по запросу. Попробуй позже или укажи запрос через /spy.")
            return

        await status_msg.edit_text("✨ Вирусный момент найден и нарезан! Наложены анимированные субтитры и баннеры. Отправляю видео в чат...")

        res = results[0]
        source_id = res.get("source_id") or "clip"
        source_title = res.get("source_title") or "Вирусный ролик"
        webpage_url = res.get("webpage_url") or ""
        clip_id = res.get("clip_id") or f"auto_{source_id}"
        ass_path = res.get("ass_path") or os.path.join("temp", f"{clip_id}_subs.ass")
        pending_clips[source_id] = {
            "title": source_title,
            "url": webpage_url,
            "clip_id": clip_id,
            "ass_path": ass_path,
            "platforms": res.get("platforms", {}),
            "res": res,
        }

        platforms = res.get("platforms", {})

        # Send Shorts
        if "shorts" in platforms:
            p_data = platforms["shorts"]
            v_path = p_data["video_path"]
            meta = p_data["metadata"]
            caption = f"🔴 YOUTUBE SHORTS\n\n{meta['title']}\n\n{meta['description']}"
            if os.path.exists(v_path):
                try:
                    await message.answer_video(
                        video=FSInputFile(v_path),
                        caption=caption[:1024]
                    )
                except Exception as ex:
                    print(f"Error sending shorts: {ex}")
                    await message.answer_video(video=FSInputFile(v_path))

        # Send TikTok
        if "tiktok" in platforms:
            p_data = platforms["tiktok"]
            v_path = p_data["video_path"]
            meta = p_data["metadata"]
            caption = f"🎵 TIKTOK\n\n{meta['description']}"
            if os.path.exists(v_path):
                try:
                    await message.answer_video(
                        video=FSInputFile(v_path),
                        caption=caption[:1024]
                    )
                except Exception as ex:
                    print(f"Error sending tiktok: {ex}")
                    await message.answer_video(video=FSInputFile(v_path))

        # Send Reels
        if "reels" in platforms:
            p_data = platforms["reels"]
            v_path = p_data["video_path"]
            meta = p_data["metadata"]
            caption = f"📸 INSTAGRAM REELS\n\n{meta['title']}\n\n{meta['description']}"
            if os.path.exists(v_path):
                try:
                    await message.answer_video(
                        video=FSInputFile(v_path),
                        caption=caption[:1024]
                    )
                except Exception as ex:
                    print(f"Error sending reels: {ex}")
                    await message.answer_video(video=FSInputFile(v_path))

        # Action button to mark as published
        kb = make_published_kb(source_id, is_pub=False)
        await message.answer(
            f"🎉 **Все 3 ролика доставлены!**\n\n"
            f"🎬 **Название:** {source_title}\n"
            f"💡 Сохраняй видео в галерею и загружай в соцсети.\n\n"
            f"👇 **Когда выложишь ролик, нажми кнопку ниже:**\n"
            f"Бот навсегда запомнит его и больше никогда не будет искать этот ролик!",
            reply_markup=kb,
            parse_mode="Markdown"
        )

    except Exception as e:
        await message.answer(f"❌ Произошла ошибка при обработке: {e}")

@dp.message(F.text.startswith("http"))
async def action_process_url(message: types.Message):
    url = message.text.strip()

    if history.is_published(url=url):
        await message.answer(
            "⚠️ **Внимание: этот ролик уже отмечен как выпущенный в вашем архиве!**\n\n"
            "Бот исключил его из работы. Если вам действительно нужно нарезать его заново, удалите его из архива через кнопку «📊 Архив выпущенных» или команду /archive.",
            reply_markup=main_kb,
            parse_mode="Markdown"
        )
        return

    status_msg = await message.answer(f"📥 Скачиваю и обрабатываю видео по ссылке: {url}...")

    loop = asyncio.get_event_loop()
    autopilot = SmartAutopilot()

    try:
        results = await loop.run_in_executor(None, lambda: autopilot.run(source=url, count=1, min_views=0))
        if not results:
            await status_msg.edit_text("❌ Ошибка при скачивании или обработке ссылки.")
            return

        res = results[0]
        source_id = res.get("source_id") or "url_clip"
        source_title = res.get("source_title") or url
        webpage_url = res.get("webpage_url") or url
        clip_id = res.get("clip_id") or f"auto_{source_id}"
        ass_path = res.get("ass_path") or os.path.join("temp", f"{clip_id}_subs.ass")
        pending_clips[source_id] = {
            "title": source_title,
            "url": webpage_url,
            "clip_id": clip_id,
            "ass_path": ass_path,
            "platforms": res.get("platforms", {}),
            "res": res,
        }

        platforms = res.get("platforms", {})
        for plat_name, p_data in platforms.items():
            v_path = p_data["video_path"]
            meta = p_data["metadata"]
            caption = f"🎬 {plat_name.upper()}\n\n{meta.get('description', '')}"
            if os.path.exists(v_path):
                try:
                    await message.answer_video(
                        video=FSInputFile(v_path),
                        caption=caption[:1024]
                    )
                except Exception as ex:
                    print(f"Error sending {plat_name}: {ex}")
                    await message.answer_video(video=FSInputFile(v_path))

        kb = make_published_kb(source_id, is_pub=False)
        await message.answer(
            "✅ **Готово! Ролики с баннерами готовы к публикации.**\n\n"
            "👇 Как только опубликуешь, нажми кнопку ниже, чтобы бот добавил его в архив:",
            reply_markup=kb,
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("spy"))
async def cmd_spy_custom(message: types.Message):
    query = message.text.replace("/spy", "").strip()
    if not query:
        await message.answer("Укажите запрос для поиска. Пример: `/spy фильм интересный отрывок`")
        return
    await message.answer(f"🔎 Ищу ролики по запросу: '{query}'...")
    loop = asyncio.get_event_loop()
    autopilot = SmartAutopilot()
    try:
        results = await loop.run_in_executor(None, lambda: autopilot.run(source=query, count=1, min_views=0))
        if results:
            res = results[0]
            source_id = res.get("source_id") or "spy_clip"
            source_title = res.get("source_title") or query
            webpage_url = res.get("webpage_url") or ""
            clip_id = res.get("clip_id") or f"auto_{source_id}"
            ass_path = res.get("ass_path") or os.path.join("temp", f"{clip_id}_subs.ass")
            pending_clips[source_id] = {
                "title": source_title,
                "url": webpage_url,
                "clip_id": clip_id,
                "ass_path": ass_path,
                "platforms": res.get("platforms", {}),
                "res": res,
            }

            for plat_name, p_data in res.get("platforms", {}).items():
                if os.path.exists(p_data["video_path"]):
                    await message.answer_video(
                        video=FSInputFile(p_data["video_path"]),
                        caption=p_data["metadata"]["description"][:1024]
                    )

            kb = make_published_kb(source_id, is_pub=False)
            await message.answer(
                "✅ **Ролики успешно отправлены!**\n\n"
                "👇 Нажми кнопку ниже, когда ролик будет опубликован:",
                reply_markup=kb,
                parse_mode="Markdown"
            )
        else:
            await message.answer("Ничего не найдено (или все найденные ролики уже в архиве опубликованных).")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

@dp.callback_query(F.data.startswith("pub:"))
async def cb_mark_published(call: types.CallbackQuery):
    source_id = call.data.split(":", 1)[1]
    info = pending_clips.get(source_id, {})
    title = info.get("title", f"Clip_{source_id}")
    url = info.get("url", "")
    history.mark_published(video_id=source_id, title=title, url=url)
    await call.answer("✅ Отлично! Ролик добавлен в архив. Он больше никогда не появится в поиске!", show_alert=True)
    try:
        await call.message.edit_reply_markup(reply_markup=make_published_kb(source_id, is_pub=True))
    except Exception:
        pass

@dp.callback_query(F.data.startswith("unpub:"))
async def cb_unmark_published(call: types.CallbackQuery):
    source_id = call.data.split(":", 1)[1]
    history.unmark_published(video_id=source_id)
    await call.answer("↩️ Ролик возвращен из архива! Теперь он снова может участвовать в поиске.", show_alert=True)
    try:
        msg_text = call.message.text or ""
        if "Архив опубликованных" in msg_text:
            items = history.get_published_list()
            count = len(items)
            if count == 0:
                await call.message.edit_text("📊 **Архив опубликованных роликов пуст.**", parse_mode="Markdown")
            else:
                inline_rows = []
                recent_items = items[-8:]
                text = f"📊 **Архив опубликованных роликов ({count} шт.):**\n\n"
                for i, it in enumerate(reversed(recent_items), 1):
                    t = it.get('title', 'Без названия')
                    date = it.get('published_at', '')
                    vid = it.get('id', '')
                    text += f"{i}. 🎬 **{t[:42]}**\n   📅 {date}\n"
                    btn_text = f"↩️ Вернуть: {t[:22]}..."
                    inline_rows.append([InlineKeyboardButton(text=btn_text, callback_data=f"unpub:{vid}")])
                text += "\n💡 *Все эти ролики навсегда исключены из поиска и рекомендаций автопилота.*"
                kb = InlineKeyboardMarkup(inline_keyboard=inline_rows) if inline_rows else None
                await call.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
        else:
            await call.message.edit_reply_markup(reply_markup=make_published_kb(source_id, is_pub=False))
    except Exception:
        pass

@dp.callback_query(F.data.startswith("info:"))
async def cb_info(call: types.CallbackQuery):
    await call.answer("Этот ролик уже в архиве опубликованных и скрыт из автопоиска.", show_alert=False)

@dp.callback_query(F.data.startswith("editsubs:"))
async def cb_edit_subtitles(call: types.CallbackQuery):
    source_id = call.data.split(":", 1)[1]
    info = pending_clips.get(source_id, {})
    clip_id = info.get("clip_id") or f"auto_{source_id}"
    ass_path = info.get("ass_path") or os.path.join("temp", f"{clip_id}_subs.ass")

    styler = SubtitleStyler()
    cues = styler.get_cues_from_ass(ass_path)
    if not cues:
        clean_id = re.sub(r'[^\w\-]', '_', clip_id).strip('_')
        for cand in [
            os.path.join("temp", f"{clean_id}_subs.ass"),
            os.path.join("temp", f"{clip_id}_subs.ass"),
            os.path.join("output", clean_id, f"{clean_id}_subs.ass"),
        ]:
            if os.path.exists(cand):
                ass_path = cand
                cues = styler.get_cues_from_ass(ass_path)
                break

    active_user_edits[call.from_user.id] = {
        "source_id": source_id,
        "clip_id": clip_id,
        "ass_path": ass_path,
        "mode": "edit",
        "time": time.time(),
    }

    if not cues:
        await call.message.answer(
            f"✏️ **Режим корректировки активирован.**\n\n"
            f"Напишите, что заменить, в формате:\n"
            f"`Старое -> Новое` (например: `босса -> босс`)\n\n"
            f"Бот обновит видео и пришлёт результат в чат!",
            parse_mode="Markdown"
        )
        await call.answer()
        return

    lines_preview = []
    for i, c in enumerate(cues[:15], 1):
        lines_preview.append(f"**{i}.** [{c['start']} - {c['end']}] {c['clean_text']}")

    txt = (
        f"📝 **Редактирование субтитров:**\n"
        f"🎬 **Ролик:** {info.get('title', 'Клип')[:45]}\n\n"
        + "\n".join(lines_preview) + "\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 **Как отправить исправления (можно ВСЁ В ОДНОМ СООБЩЕНИИ!):**\n"
        "1️⃣ **Замена слова:** `босса -> босс`\n"
        "2️⃣ **Замена реплики целиком:** `2: ОДНО СЛОВО, БОСС, И Я УЛОЖУ ЕГО`\n"
        "3️⃣ **Сдвиг тайминга:**\n"
        "   • Для всего ролика: `+0.3` (позже) или `-0.2` (раньше)\n"
        "   • Для одной реплики: `2: +0.4с` или `2: -0.3с`\n"
        "   • Точный таймкод: `2: [00:04.5 - 00:06.0] НОВЫЙ ТЕКСТ`\n\n"
        "⚡ _Отправьте сразу несколько строк в одном сообщении — бот применит все правки одновременно и пересоберёт ролик всего за 1 раз!_"
    )
    await call.message.answer(txt, parse_mode="Markdown")
    await call.answer()


@dp.callback_query(F.data.startswith("replaceword:"))
async def cb_replace_word(call: types.CallbackQuery):
    source_id = call.data.split(":", 1)[1]
    info = pending_clips.get(source_id, {})
    clip_id = info.get("clip_id") or f"auto_{source_id}"
    ass_path = info.get("ass_path") or os.path.join("temp", f"{clip_id}_subs.ass")

    active_user_edits[call.from_user.id] = {
        "source_id": source_id,
        "clip_id": clip_id,
        "ass_path": ass_path,
        "mode": "replace",
        "time": time.time(),
    }

    txt = (
        "🔤 **Быстрая замена слова во всем ролике:**\n\n"
        "Напишите, какое слово на какое заменить в формате:\n"
        "`Старое -> Новое`\n\n"
        "Примеры:\n"
        "• `босса -> босс`\n"
        "• `семь назад -> всем назад`\n"
        "• `ахи лез -> Ахиллес`\n\n"
        "⚡ Бот мгновенно заменит слово, пересоберет видео и запомнит правило в постоянный словарь!"
    )
    await call.message.answer(txt, parse_mode="Markdown")
    await call.answer()


@dp.message(Command("rules", "dict"))
async def cmd_rules(message: types.Message):
    """Displays saved user dictionary rules."""
    rules_path = "user_rules.json"
    if not os.path.exists(rules_path):
        await message.answer("📚 Словарь автозамен пока пуст. Заменяйте слова кнопкой «🔤 Заменить слово» или командой `/fix старое -> новое`!")
        return
    try:
        with open(rules_path, "r", encoding="utf-8") as f:
            rules = json.load(f)
        if not rules:
            await message.answer("📚 Словарь автозамен пока пуст.")
            return
        lines = [f"• `{old}` ➔ `{new}`" for old, new in rules.items()]
        await message.answer(f"📚 **Постоянный словарь автозамен ({len(rules)} правил):**\n\n" + "\n".join(lines) + "\n\n_Эти правила автоматически применяются ко всем новым роликам._", parse_mode="Markdown")
    except Exception as e:
        await message.answer(f"Ошибка чтения словаря: {e}")


@dp.message(F.text.startswith("/fix"))
@dp.message(F.text.contains("->") | F.text.contains("=>") | F.text.regexp(r"(?i)^[+-]\d+(?:\.\d+)?\s*с?$") | F.text.regexp(r"(?i)^(?:сдвиг|тайминг)\s*[+-]?\d+") | F.text.regexp(r"^\d+[:\.]\s*(.*)$") | F.text.regexp(r"(?i)^замени\s+(.*?)\s+на\s+(.*?)$"))
async def handle_user_correction(message: types.Message):
    raw_text = message.text.strip()
    if raw_text.startswith("/fix"):
        raw_text = raw_text.replace("/fix", "", 1).strip()

    # Determine target clip
    user_id = message.from_user.id
    edit_info = active_user_edits.get(user_id)
    source_id = None
    clip_id = None
    ass_path = None

    if edit_info and (time.time() - edit_info.get("time", 0) < 1800):
        source_id = edit_info.get("source_id")
        clip_id = edit_info.get("clip_id")
        ass_path = edit_info.get("ass_path")
    elif pending_clips:
        source_id = list(pending_clips.keys())[-1]
        c_info = pending_clips[source_id]
        clip_id = c_info.get("clip_id") or f"auto_{source_id}"
        ass_path = c_info.get("ass_path") or os.path.join("temp", f"{clip_id}_subs.ass")

    if not source_id or not clip_id:
        await message.answer("⚠️ Нет активного ролика для исправления. Нажмите «✏️ Исправить субтитры» под нужным видео.")
        return

    styler = SubtitleStyler()
    manager = ClipManager()

    clean_id = re.sub(r'[^\w\-]', '_', clip_id).strip('_')
    if not ass_path or not os.path.exists(ass_path):
        for cand in [
            os.path.join("temp", f"{clean_id}_subs.ass"),
            os.path.join("temp", f"{clip_id}_subs.ass"),
            os.path.join(manager.output_base, clean_id, f"{clean_id}_subs.ass"),
        ]:
            if os.path.exists(cand):
                ass_path = cand
                break

    if not ass_path or not os.path.exists(ass_path):
        await message.answer(f"⚠️ Не найден файл субтитров для клипа '{clip_id}'. Попробуйте нарезать ролик заново.")
        return

    # Parse all lines from user message (supports batch corrections in one go!)
    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
    global_shift = 0.0
    cue_shifts = {}
    cue_timings = {}
    cue_edits = {}
    word_replacements = []

    for line in lines:
        m_shift = re.match(r"^(?:сдвиг|тайминг)?\s*([+-]\d+(?:\.\d+)?)\s*с?(?:ек)?$", line, re.IGNORECASE)
        m_cue_shift = re.match(r"^(\d+)[:\.]\s*(?:(?:сдвиг|тайминг)?\s*([+-]\d+(?:\.\d+)?)\s*с?(?:ек)?)$", line, re.IGNORECASE)
        m_cue_time = re.match(r"^(\d+)[:\.]\s*\[\s*([\d\.:]+)\s*(?:-|–|—)\s*([\d\.:]+)\s*\]\s*(.*)$", line)
        m_cue_text = re.match(r"^(\d+)[:\.]\s*(.*)$", line)
        m_rep = re.search(r"^(?:замени\s+)?(.*?)\s*(?:->|=>|\s+на\s+)\s*(.*?)$", line, re.IGNORECASE)

        if m_shift and not m_rep:
            try:
                global_shift += float(m_shift.group(1))
            except ValueError:
                pass
        elif m_cue_shift:
            try:
                idx = int(m_cue_shift.group(1))
                shift_v = float(m_cue_shift.group(2))
                cue_shifts[idx] = shift_v
            except ValueError:
                pass
        elif m_cue_time:
            try:
                from subtitle_styler import parse_time_to_seconds
                idx = int(m_cue_time.group(1))
                s_val = parse_time_to_seconds(m_cue_time.group(2))
                e_val = parse_time_to_seconds(m_cue_time.group(3))
                cue_timings[idx] = (s_val, e_val)
                txt_part = m_cue_time.group(4).strip()
                if txt_part:
                    cue_edits[idx] = txt_part
            except Exception:
                pass
        elif m_rep and not m_cue_text:
            old_w = m_rep.group(1).strip()
            new_w = m_rep.group(2).strip()
            if old_w and new_w:
                word_replacements.append((old_w, new_w))
                save_user_rule(old_w, new_w)
        elif m_cue_text:
            try:
                idx = int(m_cue_text.group(1))
                new_t = m_cue_text.group(2).strip()
                if new_t:
                    cue_edits[idx] = new_t
            except ValueError:
                pass
        elif m_rep:
            old_w = m_rep.group(1).strip()
            new_w = m_rep.group(2).strip()
            if old_w and new_w:
                word_replacements.append((old_w, new_w))
                save_user_rule(old_w, new_w)

    has_any = bool(word_replacements or cue_edits or cue_shifts or cue_timings or abs(global_shift) > 0.001)
    if not has_any:
        await message.answer(
            "💡 **Форматы исправлений (можно отправить всё в одном сообщении):**\n"
            "• `босса -> босс` — замена слова во всем ролике\n"
            "• `2: НОВЫЙ ТЕКСТ` — изменить реплику #2\n"
            "• `+0.3с` или `-0.2с` — сдвинуть все субтитры ролика\n"
            "• `3: +0.4с` — сдвинуть только реплику #3\n"
            "• `2: [00:04.5 - 00:06.0] ТЕКСТ` — точный таймкод",
            parse_mode="Markdown"
        )
        return

    status_msg = await message.answer("🔄 Применяю все правки и пересобираю видео... (обычно ~20–30 сек)")

    # Execute all batch modifications atomically in one pass
    batch_res = styler.apply_batch_modifications_to_ass(
        ass_path=ass_path,
        replacements=word_replacements,
        cue_edits=cue_edits,
        cue_shifts=cue_shifts,
        cue_timings=cue_timings,
        global_shift=global_shift
    )

    if not batch_res.get("modified", False):
        await status_msg.edit_text("⚠️ Не удалось применить изменения к файлу субтитров.")
        return

    loop = asyncio.get_event_loop()
    try:
        re_results = await loop.run_in_executor(None, lambda: manager.re_render_clip(clip_id, new_ass_path=ass_path))
        platforms = re_results.get("platforms", {})
        if not platforms:
            await status_msg.edit_text("❌ Ошибка при перерендере видео.")
            return

        await status_msg.edit_text("✨ Видео успешно пересобрано! Отправляю обновленный ролик...")

        if "shorts" in platforms:
            p_data = platforms["shorts"]
            if os.path.exists(p_data["video_path"]):
                safe_vid = ensure_video_under_telegram_limit(p_data["video_path"])
                caption = f"🔴 ОБНОВЛЕННЫЙ YOUTUBE SHORTS\n\n{p_data['metadata']['title']}\n\n{p_data['metadata']['description']}"
                await message.answer_video(video=FSInputFile(safe_vid), caption=caption[:1024])

        if "tiktok" in platforms:
            p_data = platforms["tiktok"]
            if os.path.exists(p_data["video_path"]):
                safe_vid = ensure_video_under_telegram_limit(p_data["video_path"])
                caption = f"🎵 ОБНОВЛЕННЫЙ TIKTOK\n\n{p_data['metadata']['description']}"
                await message.answer_video(video=FSInputFile(safe_vid), caption=caption[:1024])

        kb = make_published_kb(source_id, is_pub=False)
        from subtitle_styler import seconds_to_ass_time
        report_lines = []
        for old_w, new_w in word_replacements:
            report_lines.append(f"• 🔤 Замена слова: «{old_w}» ➔ «{new_w}» *(сохранено в словарь)*")
        if abs(global_shift) > 0.001:
            sign = "+" if global_shift > 0 else ""
            report_lines.append(f"• ⏱️ Общий сдвиг тайминга: `{sign}{global_shift:.2f} сек`")
        for idx, shift in cue_shifts.items():
            sign = "+" if shift > 0 else ""
            report_lines.append(f"• ⏱️ Сдвиг реплики #{idx}: `{sign}{shift:.2f} сек`")
        for idx, txt in cue_edits.items():
            report_lines.append(f"• 📝 Реплика #{idx} обновлена: «{txt[:30]}»")
        for idx, (s, e) in cue_timings.items():
            report_lines.append(f"• 🎯 Таймкод реплики #{idx}: `[{seconds_to_ass_time(s)} - {seconds_to_ass_time(e)}]`")

        report = (
            f"🎉 **Субтитры успешно обновлены ({len(report_lines)} правок за 1 раз):**\n\n"
            + "\n".join(report_lines) + "\n\n"
            "⚡ _Ролик пересобран и отправлен выше!_\n"
            "👇 Когда ролик будет опубликован, нажмите кнопку ниже:"
        )
        await message.answer(report, reply_markup=kb, parse_mode="Markdown")

        if user_id in active_user_edits:
            del active_user_edits[user_id]

    except Exception as ex:
        await status_msg.edit_text(f"❌ Ошибка перерендера: {ex}")

async def _init_tunnel(tunnel: TunnelManager, web_srv: MovieEditorWebServer):
    public_url = await tunnel.start()
    if public_url:
        web_srv.public_url = public_url
        print(f"📱 Telegram Mini App готов! Публичный HTTPS URL: {public_url}/webapp", flush=True)

async def run_bot():
    global web_server_instance, tunnel_instance
    cfg = load_config()
    token = cfg.get("telegram", {}).get("bot_token")
    if not token or token.startswith("YOUR_"):
        print("\n❌ ВНИМАНИЕ: Для работы Telegram-бота укажите токен в файле config.json ('telegram' -> 'bot_token').", flush=True)
        return

    bot = Bot(token=token)
    me = await bot.get_me()
    print(f"🤖 Telegram-бот @{me.username} успешно запущен и слушает команды! Напишите ему /start в Telegram.", flush=True)

    # Initialize Web Server for Mini App
    web_server_instance = MovieEditorWebServer(
        bot=bot,
        pending_clips=pending_clips,
        port=8080,
        bot_token=token,
        allowed_users_provider=get_allowed_users,
    )
    await web_server_instance.start()

    # Initialize Cloudflare Tunnel for mobile HTTPS
    tunnel_instance = TunnelManager(port=8080)
    asyncio.create_task(_init_tunnel(tunnel_instance, web_server_instance))

    try:
        await dp.start_polling(bot)
    finally:
        if web_server_instance:
            await web_server_instance.stop()
        if tunnel_instance:
            await tunnel_instance.stop()

if __name__ == "__main__":
    asyncio.run(run_bot())
