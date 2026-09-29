"""
Web Server and REST API for Telegram Mini App (TMA).
Runs asynchronously on aiohttp inside the bot's event loop.
Provides:
- Static HTML/CSS/JS delivery for Telegram WebApp
- HTTP 206 Partial Content video streaming for smooth seeking
- Cue inspection and real-time ASS subtitle saving
- Instant FFmpeg re-render and automatic Telegram delivery
"""

import os
import sys
import re
import json
import asyncio
import logging
import base64
import binascii
import hashlib
import hmac
import time
from urllib.parse import parse_qsl
from typing import Callable, Dict, Any, List, Optional
from aiohttp import web
from aiogram import Bot
from aiogram.types import FSInputFile

from subtitle_styler import SubtitleStyler, parse_time_to_seconds, seconds_to_ass_time
from clip_manager import ClipManager
from grammar_corrector import save_user_rule

logger = logging.getLogger("web_server")

TMA_AUTH_MAX_AGE_SECONDS = 3600
TMA_AUTH_FUTURE_SKEW_SECONDS = 30
TMA_AUTH_COOKIE = "tma_init_data"


def validate_telegram_init_data(
    init_data: str,
    bot_token: str,
    max_age_seconds: int = TMA_AUTH_MAX_AGE_SECONDS,
    now: Optional[int] = None,
) -> Dict[str, Any]:
    """Validate Telegram WebApp initData and return its authenticated user."""
    if not init_data or not bot_token:
        raise ValueError("Missing Telegram authorization data")

    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise ValueError("Invalid Telegram authorization data") from exc

    values: Dict[str, str] = {}
    for key, value in pairs:
        if key in values:
            raise ValueError("Duplicate Telegram authorization field")
        values[key] = value

    if not values.get("hash") or not values.get("user") or not values.get("auth_date"):
        raise ValueError("Incomplete Telegram authorization data")

    received_hash = values.pop("hash")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", received_hash):
        raise ValueError("Invalid Telegram authorization hash")

    data_check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret_key = hmac.new(
        b"WebAppData",
        bot_token.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    expected_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash.lower()):
        raise ValueError("Invalid Telegram authorization signature")

    try:
        auth_date = int(values["auth_date"])
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid Telegram authorization date") from exc

    current_time = int(time.time()) if now is None else int(now)
    if auth_date > current_time + TMA_AUTH_FUTURE_SKEW_SECONDS:
        raise ValueError("Telegram authorization date is in the future")
    if current_time - auth_date > max_age_seconds:
        raise ValueError("Telegram authorization data has expired")

    try:
        user = json.loads(values["user"])
        user_id = user.get("id")
        if isinstance(user_id, bool):
            raise ValueError
        user_id = int(user_id)
        if user_id <= 0:
            raise ValueError
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid Telegram user data") from exc

    user["id"] = user_id
    return user

def parse_ass_dialogue_line(line: str, cue_id: int) -> Optional[Dict[str, Any]]:
    """Parses ASS Dialogue event line into cue object with word-level timing."""
    # Dialogue: Marked, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
    if not line.startswith("Dialogue:"):
        return None
    parts = line[len("Dialogue:"):].split(",", 9)
    if len(parts) < 10:
        return None
    
    start_str = parts[1].strip()
    end_str = parts[2].strip()
    text_raw = parts[9].strip()

    try:
        s_sec = parse_time_to_seconds(start_str)
        e_sec = parse_time_to_seconds(end_str)
    except Exception:
        return None

    cue_dur = max(0.1, e_sec - s_sec)

    # Parse individual words and their relative timings for the web player
    words_data = []
    tokens = re.findall(r"(\{[^\}]*\})?([^\s\{]+)", text_raw)
    for i, (tags, w_text) in enumerate(tokens):
        w_text_clean = w_text.strip()
        if not w_text_clean:
            continue
        if i == 0:
            rel_s = 0.0
        else:
            m_start = re.search(r"\\t\((\d+),\d+,\\c", tags)
            if m_start:
                rel_s = float(m_start.group(1)) / 1000.0
            else:
                rel_s = i * (cue_dur / max(1, len(tokens)))

        words_data.append({
            "word": w_text_clean,
            "rel_start": round(rel_s, 2),
        })

    for idx in range(len(words_data)):
        if idx < len(words_data) - 1:
            words_data[idx]["rel_end"] = words_data[idx + 1]["rel_start"]
        else:
            words_data[idx]["rel_end"] = round(cue_dur, 2)

    # Strip ASS override tags like {\an5...}
    text_clean = re.sub(r"\{.*?\}", "", text_raw)
    text_clean = text_clean.replace(r"\N", " ").replace(r"\n", " ").strip()

    return {
        "id": cue_id,
        "start": round(s_sec, 2),
        "end": round(e_sec, 2),
        "text": text_clean.upper(),
        "raw_text": text_raw,
        "words": words_data
    }

class MovieEditorWebServer:
    def __init__(
        self,
        bot: Optional[Bot] = None,
        pending_clips: Optional[Dict[str, Any]] = None,
        public_url: Optional[str] = None,
        port: int = 8080,
        host: str = "0.0.0.0",
        bot_token: Optional[str] = None,
        allowed_users_provider: Optional[Callable[[], List[int]]] = None,
    ):
        self.bot = bot
        self.pending_clips = pending_clips if pending_clips is not None else {}
        self.public_url = public_url
        self.port = port
        self.host = host
        self.bot_token = bot_token
        self.allowed_users_provider = allowed_users_provider or (lambda: [])
        self.styler = SubtitleStyler()
        self.manager = ClipManager()
        self.app = web.Application(middlewares=[self.telegram_auth_middleware])
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        self._setup_routes()

    @web.middleware
    async def telegram_auth_middleware(self, request: web.Request, handler):
        if not (request.path.startswith("/api/") or request.path.startswith("/media/")):
            return await handler(request)

        init_data = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.lower().startswith("tma "):
            init_data = auth_header[4:].strip()
        elif request.cookies.get(TMA_AUTH_COOKIE):
            try:
                encoded = request.cookies[TMA_AUTH_COOKIE]
                padding = "=" * (-len(encoded) % 4)
                init_data = base64.urlsafe_b64decode(encoded + padding).decode("utf-8")
            except (binascii.Error, ValueError, UnicodeDecodeError):
                init_data = None

        try:
            telegram_user = validate_telegram_init_data(init_data or "", self.bot_token or "")
        except ValueError:
            return web.json_response({"success": False, "error": "Unauthorized"}, status=401)

        allowed_users = self.allowed_users_provider()
        if telegram_user["id"] not in allowed_users:
            return web.json_response({"success": False, "error": "Forbidden"}, status=403)

        request["telegram_user"] = telegram_user
        response = await handler(request)

        if auth_header.lower().startswith("tma "):
            encoded = base64.urlsafe_b64encode(init_data.encode("utf-8")).decode("ascii").rstrip("=")
            response.set_cookie(
                TMA_AUTH_COOKIE,
                encoded,
                max_age=TMA_AUTH_MAX_AGE_SECONDS,
                httponly=True,
                secure=True,
                samesite="Strict",
                path="/",
            )
        return response

    def _setup_routes(self):
        # Static files
        self.app.router.add_get("/", self.handle_webapp_index)
        self.app.router.add_get("/webapp", self.handle_webapp_index)
        self.app.router.add_get("/style.css", self.handle_static_css)
        self.app.router.add_get("/app.js", self.handle_static_js)

        # REST API
        self.app.router.add_get("/api/clips", self.handle_get_clips)
        self.app.router.add_get("/api/clip/{clip_id}", self.handle_get_clip_details)
        self.app.router.add_get("/media/{clip_id}/video", self.handle_stream_video)
        self.app.router.add_post("/api/clip/{clip_id}/save", self.handle_save_clip)
        self.app.router.add_post("/api/rules/add", self.handle_add_rule)

    async def handle_webapp_index(self, request: web.Request) -> web.Response:
        index_path = os.path.join(os.path.dirname(__file__), "webapp", "index.html")
        if not os.path.exists(index_path):
            return web.Response(text="Webapp index.html not found", status=404)
        return web.FileResponse(index_path)

    async def handle_static_css(self, request: web.Request) -> web.Response:
        css_path = os.path.join(os.path.dirname(__file__), "webapp", "style.css")
        return web.FileResponse(css_path)

    async def handle_static_js(self, request: web.Request) -> web.Response:
        js_path = os.path.join(os.path.dirname(__file__), "webapp", "app.js")
        return web.FileResponse(js_path)

    def _find_clip_files(self, clip_id: str) -> Dict[str, Optional[str]]:
        clean_id = re.sub(r'[^\w\-]', '_', clip_id).strip('_')
        raw_id = clean_id.replace("auto_", "")

        # Candidates for ASS subtitles
        ass_candidates = [
            os.path.join("temp", f"{clean_id}_subs.ass"),
            os.path.join("temp", f"{clip_id}_subs.ass"),
            os.path.join("temp", f"{raw_id}_subs.ass"),
            os.path.join(self.manager.output_base, clean_id, f"{clean_id}_subs.ass"),
            os.path.join(self.manager.output_base, clean_id, f"{raw_id}_subs.ass"),
        ]
        ass_path = None
        for p in ass_candidates:
            if os.path.exists(p):
                ass_path = p
                break

        # Candidates for Video (prefer vertical shorts, then tiktok, reels, or source)
        vid_candidates = [
            os.path.join(self.manager.output_base, clean_id, f"{clean_id}_shorts.mp4"),
            os.path.join(self.manager.output_base, clean_id, f"{clean_id}_tiktok.mp4"),
            os.path.join(self.manager.output_base, clean_id, f"{clean_id}_reels.mp4"),
            os.path.join("temp", f"source_{raw_id}.mp4"),
            os.path.join("temp", f"source_{clean_id}.mp4"),
        ]
        vid_path = None
        for p in vid_candidates:
            if os.path.exists(p):
                vid_path = p
                break

        # Summary JSON
        summary_path = os.path.join(self.manager.output_base, clean_id, "clip_summary.json")

        return {
            "clean_id": clean_id,
            "raw_id": raw_id,
            "ass_path": ass_path,
            "vid_path": vid_path,
            "summary_path": summary_path if os.path.exists(summary_path) else None
        }

    async def handle_get_clips(self, request: web.Request) -> web.Response:
        """Returns list of all available clips."""
        clips = []
        seen = set()

        # 1. From pending_clips memory
        for src_id, info in self.pending_clips.items():
            cid = info.get("clip_id") or f"auto_{src_id}"
            seen.add(cid)
            clips.append({
                "id": cid,
                "title": info.get("title", cid),
                "film": info.get("film", "Кино"),
                "code": info.get("code", "777"),
                "has_video": True
            })

        # 2. From output directory
        if os.path.exists(self.manager.output_base):
            for entry in sorted(os.scandir(self.manager.output_base), key=lambda e: e.stat().st_mtime, reverse=True):
                if entry.is_dir() and entry.name.startswith("auto_") and entry.name not in seen:
                    cid = entry.name
                    files = self._find_clip_files(cid)
                    title = cid
                    film = "Кино"
                    code = "777"
                    if files["summary_path"]:
                        try:
                            with open(files["summary_path"], "r", encoding="utf-8") as sf:
                                sdata = json.load(sf)
                                title = sdata.get("hook_title") or sdata.get("title") or cid
                                film = sdata.get("movie_title") or film
                                code = sdata.get("movie_code") or code
                        except Exception:
                            pass
                    
                    clips.append({
                        "id": cid,
                        "title": title,
                        "film": film,
                        "code": code,
                        "has_video": bool(files["vid_path"])
                    })
                    seen.add(cid)

        return web.json_response({"clips": clips})

    async def handle_get_clip_details(self, request: web.Request) -> web.Response:
        clip_id = request.match_info["clip_id"]
        files = self._find_clip_files(clip_id)

        title = clip_id
        film = "Кино"
        code = "777"
        if files["summary_path"]:
            try:
                with open(files["summary_path"], "r", encoding="utf-8") as sf:
                    sdata = json.load(sf)
                    title = sdata.get("hook_title") or sdata.get("title") or clip_id
                    film = sdata.get("movie_title") or film
                    code = sdata.get("movie_code") or code
            except Exception:
                pass

        cues = []
        if files["ass_path"]:
            try:
                with open(files["ass_path"], "r", encoding="utf-8", errors="replace") as f:
                    cue_idx = 1
                    for line in f:
                        line = line.strip()
                        cue = parse_ass_dialogue_line(line, cue_idx)
                        if cue:
                            cues.append(cue)
                            cue_idx += 1
            except Exception as e:
                logger.error(f"Error reading ASS file: {e}")

        return web.json_response({
            "id": clip_id,
            "title": title,
            "film": film,
            "code": code,
            "has_video": bool(files["vid_path"]),
            "cues": cues
        })

    async def handle_stream_video(self, request: web.Request) -> web.StreamResponse:
        clip_id = request.match_info["clip_id"]
        files = self._find_clip_files(clip_id)
        vid_path = files["vid_path"]

        if not vid_path or not os.path.exists(vid_path):
            return web.Response(text="Video file not found", status=404)

        # FileResponse in aiohttp natively supports HTTP 206 Partial Content (seeking)!
        return web.FileResponse(vid_path)

    async def handle_save_clip(self, request: web.Request) -> web.Response:
        clip_id = request.match_info["clip_id"]
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"success": False, "error": "Invalid JSON"}, status=400)

        global_shift = float(data.get("global_shift", 0.0))
        cues_data = data.get("cues", [])
        user_id = request["telegram_user"]["id"]

        files = self._find_clip_files(clip_id)
        ass_path = files["ass_path"]
        if not ass_path or not os.path.exists(ass_path):
            return web.json_response({"success": False, "error": "Subtitles file not found"}, status=404)

        # Build modifications map
        cue_timings = {}
        cue_edits = {}
        for c in cues_data:
            c_id = c.get("id")
            s = float(c.get("start", 0))
            e = float(c.get("end", 0))
            t = str(c.get("text", "")).strip().upper()
            if c_id:
                cue_timings[c_id] = (s, e)
                if t:
                    cue_edits[c_id] = t

        # Atomically apply to ASS file
        batch_res = self.styler.apply_batch_modifications_to_ass(
            ass_path=ass_path,
            replacements=[],
            cue_edits=cue_edits,
            cue_shifts={},
            cue_timings=cue_timings,
            global_shift=global_shift
        )

        if not batch_res.get("modified", False):
            return web.json_response({"success": False, "error": "No modifications applied"}, status=400)

        # Trigger fast cached FFmpeg re-render in background executor
        loop = asyncio.get_event_loop()
        try:
            re_results = await loop.run_in_executor(
                None,
                lambda: self.manager.re_render_clip(clip_id, new_ass_path=ass_path)
            )
        except Exception as e:
            logger.error(f"Re-render failed: {e}")
            return web.json_response({"success": False, "error": f"Re-render error: {e}"}, status=500)

        # Deliver only to the user authenticated by Telegram WebApp initData.
        if self.bot:
            asyncio.create_task(self._deliver_to_telegram(user_id, clip_id, re_results, global_shift, len(cue_edits)))

        return web.json_response({
            "success": True,
            "message": "Ролик успешно пересобран!",
            "modified_cues": len(cue_edits),
            "global_shift": global_shift
        })

    async def _deliver_to_telegram(self, user_id: int, clip_id: str, re_results: Dict[str, Any], global_shift: float, edits_count: int):
        try:
            from telegram_bot import ensure_video_under_telegram_limit
            platforms = re_results.get("platforms", {})
            if "shorts" in platforms:
                p = platforms["shorts"]
                if os.path.exists(p["video_path"]):
                    safe_v = ensure_video_under_telegram_limit(p["video_path"])
                    caption = f"📱 ОБНОВЛЕНО ЧЕРЕЗ MINI APP (YOUTUBE SHORTS)\n\n{p['metadata']['title']}\n\n{p['metadata']['description']}"
                    await self.bot.send_video(chat_id=user_id, video=FSInputFile(safe_v), caption=caption[:1024])

            if "tiktok" in platforms:
                p = platforms["tiktok"]
                if os.path.exists(p["video_path"]):
                    safe_v = ensure_video_under_telegram_limit(p["video_path"])
                    caption = f"🎵 ОБНОВЛЕНО ЧЕРЕЗ MINI APP (TIKTOK)\n\n{p['metadata']['description']}"
                    await self.bot.send_video(chat_id=user_id, video=FSInputFile(safe_v), caption=caption[:1024])

            summary_text = (
                f"✅ **Ролик успешно пересобран через Mini App!**\n"
                f"• Применено правок реплик: `{edits_count}`\n"
                f"• Общий сдвиг тайминга: `{global_shift:+.2f} сек`\n\n"
                f"⚡ Видео доставлено выше."
            )
            await self.bot.send_message(chat_id=user_id, text=summary_text, parse_mode="Markdown")
        except Exception as ex:
            logger.error(f"Error delivering to telegram: {ex}")

    async def handle_add_rule(self, request: web.Request) -> web.Response:
        data = await request.json()
        old_w = data.get("old", "").strip()
        new_w = data.get("new", "").strip()
        if old_w and new_w:
            save_user_rule(old_w, new_w)
            return web.json_response({"success": True})
        return web.json_response({"success": False, "error": "Empty rule"}, status=400)

    async def start(self):
        """Starts the aiohttp server."""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.host, self.port)
        await self.site.start()
        logger.info(f"🌐 Web Server запущен на http://localhost:{self.port}")

    async def stop(self):
        """Stops the aiohttp server."""
        if self.runner:
            await self.runner.cleanup()
            self.runner = None
            logger.info("🛑 Web Server остановлен.")
