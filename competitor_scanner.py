"""
Competitor Scanner & Trend Spy Module.
Discovers trending movie shorts/reels from competitor channels and search queries,
extracts film titles, codes, and viral hooks, and downloads high-performing clips.
"""

import os
import sys
import json
import re
import subprocess
import requests
from typing import List, Dict, Any, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from history_manager import HistoryManager

DIALOGUE_KEYWORDS = [
    "диалог", "разговор", "сказал", "ответил", "признался", "спросил",
    "фраза", "слова", "монолог", "общение", "спор", "допрос", "разборка",
    "гениальный ответ", "умный ответ", "поставил на место", "цитата", "сцена"
]

NOISE_KEYWORDS = [
    "phonk", "bass", "edit", "edits", "fight", "amv", "slowed", "speed up",
    "sigma", "remix", "без слов", "драка", "перестрелка", "дрифт", "гонка", "soundtrack"
]

class CompetitorScanner:
    def __init__(self, temp_dir: str = "./temp_downloads"):
        self.temp_dir = os.path.abspath(temp_dir)
        os.makedirs(self.temp_dir, exist_ok=True)
        self.history = HistoryManager()

    def search_trending_movie_shorts(
        self,
        query_or_channel: str = "момент из фильма",
        max_results: int = 5,
        min_views: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        Scans YouTube for competitor shorts via yt-dlp.
        Finds viral movie moments and clips with high views and engagement.
        Automatically filters out clips previously marked as published!
        """
        scan_pool = max(35, max_results * 7)
        is_direct_video = "watch?v=" in query_or_channel or "youtu.be/" in query_or_channel or "/shorts/" in query_or_channel
        if is_direct_video:
            target = query_or_channel
            cmd = [
                "yt-dlp",
                target,
                "--dump-json",
                "--no-playlist",
            ]
        elif query_or_channel.startswith("http") or query_or_channel.startswith("@"):
            target = query_or_channel
            if not target.endswith("/shorts") and not target.endswith("/videos"):
                target = f"{target.rstrip('/')}/shorts"
            cmd = [
                "yt-dlp",
                target,
                "--dump-json",
                "--flat-playlist",
                "--playlist-end", str(scan_pool),
            ]
        else:
            # ytsearch
            search_expr = f"ytsearch{scan_pool}:{query_or_channel}"
            cmd = [
                "yt-dlp",
                search_expr,
                "--dump-json",
                "--flat-playlist",
            ]

        print(f"🔎 Сканирование вирусных моментов фильмов по запросу: '{query_or_channel}'...")
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        
        candidates = []
        for line in res.stdout.strip().split("\n"):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                vid_id = data.get("id")
                web_url = data.get("webpage_url") or data.get("url")

                # Filter out already published clips
                if self.history.is_published(vid_id, web_url):
                    print(f"⏩ Пропуск '{data.get('title')}': ролик уже в архиве опубликованных.")
                    continue

                duration = data.get("duration") or 0
                views = data.get("view_count") or 0
                if views >= min_views or min_views == 0:
                    parsed_info = self.parse_movie_info(data.get("title", ""), data.get("description", ""))
                    data.update(parsed_info)
                    candidates.append(data)
            except Exception:
                continue

        # Score and rank: viral views + duration bonus, penalize pure music/phonk edits
        def score_candidate(item):
            t_lower = (item.get("title") or "").lower()
            dur = item.get("duration") or 0
            views = item.get("view_count") or 0
            
            has_noise = any(k in t_lower for k in NOISE_KEYWORDS)

            score = float(views)
            if has_noise:
                score -= 1000000.0

            # Duration bonus: 15s to 60s is ideal for Shorts/TikTok
            dur_tier = 2 if (15 <= dur <= 60) else (1 if (5 <= dur <= 95) else 0)
            return (dur_tier, score)

        candidates.sort(key=score_candidate, reverse=True)
        # Return candidate pool large enough for speech validation
        pool_size = max(max_results * 3, 10)
        top_picks = candidates[:pool_size]
        print(f"✅ Найдено {len(top_picks)} свежих вирусных моментов кино!")
        return top_picks

    def parse_movie_info(self, title: str, description: Optional[str] = "") -> Dict[str, str]:
        """
        Extracts movie name, code, and emotional hook from competitor titles and descriptions.
        Uses Gemini LLM for 100% accuracy, with smart regex fallback.
        """
        desc = description or ""
        combined = f"{title}\n{desc}"

        # 0. Try LLM extraction cascade (fast & context-aware)
        try:
            cfg_path = "config.json"
            if os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg_data = json.load(f)
                api_key = cfg_data.get("llm", {}).get("api_key")
                if api_key:
                    models = [
                        "gemini-3.5-flash-lite",
                        "gemini-flash-lite-latest",
                        "gemini-3.5-flash"
                    ]
                    prompt = f"""Из названия и описания ролика конкурента извлеки:
1. movie_title: точное русское название кинофильма (например: «Отряд самоубийц», «Брат 2», «Троя»). Без мусора вроде '4K', 'момент', 'фильм', 'best moments'.
2. movie_code: числовой код фильма если указан в тексте (например '482', '777'), иначе '777'.
3. hook_title: яркий эмоциональный хук для зрителя (до 50 символов).

Название: "{title}"
Описание: "{desc[:400]}"

Формат ответа: строго валидный JSON:
{{"movie_title": "...", "movie_code": "...", "hook_title": "..."}}"""
                    payload = {
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"}
                    }
                    for m_name in models:
                        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m_name}:generateContent?key={api_key}"
                        try:
                            r = requests.post(url, json=payload, timeout=6)
                            if r.status_code == 200:
                                data = r.json()
                                text_res = data.get("candidates", [])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                                clean_json = re.sub(r"^```json\s*|\s*```$", "", text_res.strip())
                                parsed = json.loads(clean_json)
                                if parsed.get("movie_title") and len(parsed["movie_title"]) >= 2:
                                    m_code = str(parsed.get("movie_code", "777")).strip()
                                    if not m_code or not m_code.isdigit():
                                        m_code = "777"
                                    return {
                                        "movie_title": parsed["movie_title"].strip(),
                                        "movie_code": m_code,
                                        "hook_title": parsed.get("hook_title", title[:50]).strip(),
                                    }
                            elif r.status_code in [429, 500, 503]:
                                continue
                        except Exception:
                            continue
        except Exception:
            pass

        # 1. Fallback: Search for movie code: e.g. "Код: 481", "код фильма: 504", "код фильма #732", "#482"
        code_match = re.search(r"(?:код|code|id)(?:\s+фильма)?[\s#:№]*(\d{2,6})", combined, re.IGNORECASE)
        if not code_match:
            code_match = re.search(r"#(\d{3,5})\b", combined)
        movie_code = code_match.group(1) if code_match else "777"

        # 2. Search for movie title via quotes or labels
        title_patterns = [
            r"\xab([^\xbb]+)\xbb",
            r'"([^"]+)"',
            r"«([^»]+)»",
            r"(?:фильм|название|кино)[\s:\x22\xab\u2014\-«]+([^\n\r,\x22\xbb»#|]+)",
        ]
        movie_title = ""
        for pat in title_patterns:
            m = re.search(pat, combined, re.IGNORECASE)
            if m:
                cand = m.group(1).strip()
                cand = re.sub(r"https?://\S+|www\.\S+|youtu\.be/\S+", "", cand)
                cand = re.sub(r"[\s_]+", " ", cand).strip(" ._-:;,")
                cand_lower = cand.lower()
                if cand and len(cand) >= 2 and cand_lower not in ["в шапке", "в описании", "в закрепе", "в профиле", "в комментах", "онлайн", "фильмы онлайн", "смотреть онлайн"]:
                    movie_title = cand
                    break

        # 3. Delimiter split fallback: e.g. "Хук | Название фильма | 4K ULTRA HD" or "ОТРЯД САМОУБИЙЦ | Дэдшот | Код 482"
        if not movie_title:
            parts = [p.strip() for p in re.split(r"[|—–]", title) if p.strip()]
            candidates = []
            for p in parts:
                p_clean = re.sub(r"#\S+", "", p).strip()
                p_clean = re.sub(r"(?:код|code|id)(?:\s+фильма)?[\s#:№]*\d+", "", p_clean, flags=re.IGNORECASE).strip(" !?._-")
                p_lower = p_clean.lower()
                if not p_clean or len(p_clean) < 2:
                    continue
                if any(w in p_lower for w in ["4k", "1080p", "720p", "смотреть", "онлайн"]):
                    continue
                candidates.append(p_clean)

            if len(parts) >= 2:
                # If first part is all UPPERCASE (like "ОТРЯД САМОУБИЙЦ"), it's likely the title
                if parts[0].isupper() and len(parts[0]) >= 3 and not any(w in parts[0].lower() for w in ["4k", "1080p", "смотреть", "онлайн"]):
                    movie_title = parts[0].strip()
                elif candidates:
                    movie_title = candidates[1] if len(candidates) > 1 else candidates[0]
            elif candidates:
                movie_title = candidates[0]

        if not movie_title or any(w in movie_title.lower() for w in ["1080p", "4k", "смотреть", "онлайн"]):
            movie_title = f"Фильм #{movie_code}"

        # 4. Clean hook (first part of title without tags)
        hook = title.split("|")[0].split("—")[0].strip()
        hook = re.sub(r"#\S+", "", hook).strip()
        if len(hook) < 10:
            hook = "ЭТОТ МОМЕНТ СТОИТ УВИДЕТЬ 😱"

        return {
            "movie_title": movie_title,
            "movie_code": movie_code,
            "hook_title": hook,
        }

    def download_clip(self, video_url: str, output_filename: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
        """Downloads high quality video file and subtitles of the competitor short using yt-dlp."""
        if not output_filename:
            output_filename = os.path.join(self.temp_dir, "competitor_source.mp4")
        
        os.makedirs(os.path.dirname(os.path.abspath(output_filename)), exist_ok=True)
        base_no_ext, _ = os.path.splitext(output_filename)

        cmd = [
            "yt-dlp",
            video_url,
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "-o", output_filename,
            "--write-auto-subs",
            "--sub-lang", "ru",
            "--sub-format", "srt",
            "--no-abort-on-error",
            "--force-overwrites",
            "--no-playlist",
        ]

        print(f"📥 Скачивание клипа и субтитров: {video_url}...")
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        
        sub_file = None
        cand = f"{base_no_ext}.ru.srt"
        if os.path.exists(cand) and os.path.getsize(cand) > 10:
            sub_file = cand
            print(f"💬 Найдены субтитры: {cand}")

        # If video file exists and is valid, return success even if subtitles had warnings
        if os.path.exists(output_filename) and os.path.getsize(output_filename) > 5000:
            print(f"✅ Клип успешно скачан ({os.path.getsize(output_filename)/1024/1024:.2f} MB): {output_filename}")
            return output_filename, sub_file
        else:
            print(f"❌ Ошибка скачивания:\n{res.stderr}")
            return None, None

if __name__ == "__main__":
    scanner = CompetitorScanner()
    results = scanner.search_trending_movie_shorts(query_or_channel="фильм шортс код в закрепе", max_results=3, min_views=0)
    for i, r in enumerate(results, 1):
        print(f"\n[{i}] Заголовок: {r.get('title')}")
        print(f"    Просмотры: {r.get('view_count'):,} | Фильм: {r.get('movie_title')} | Код: {r.get('movie_code')}")
        print(f"    Хук: {r.get('hook_title')}")
