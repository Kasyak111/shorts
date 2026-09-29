"""
Clip Manager & Automation Pipeline.
Orchestrates banner creation, video rendering, metadata generation,
and platform exports for YouTube Shorts, TikTok, and Instagram Reels.
"""

import os
import sys
import json
import re
from typing import Dict, Any, List, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from banner_templates import BannerGenerator
from video_processor import VideoProcessor
from subtitle_styler import SubtitleStyler

class ClipManager:
    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.config = self._load_config()
        self.banner_gen = BannerGenerator()
        self.video_proc = VideoProcessor()
        self.sub_styler = SubtitleStyler()
        
        self.output_base = os.path.abspath(self.config.get("output_dir", "./output"))
        self.temp_dir = os.path.abspath(self.config.get("temp_dir", "./temp"))
        os.makedirs(self.output_base, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)

    def _load_config(self) -> Dict[str, Any]:
        if os.path.exists(self.config_path):
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def generate_metadata(
        self,
        platform: str,
        title: str,
        movie_title: str,
        movie_code: str,
    ) -> Dict[str, str]:
        """Generates platform-optimized titles, descriptions, and hashtags."""
        # Sanitize incoming title: strip competitor links, URLs and Telegram handles to prevent spam bans
        clean_title = re.sub(r"https?://\S+|www\.\S+|t\.me/\S+|@[a-zA-Z0-9_]+", "", title)
        clean_title = re.sub(r"\s+", " ", clean_title).strip()
        title = clean_title or "Эпичный момент"

        plat_cfg = self.config.get("platforms", {}).get(platform, {})
        tags = plat_cfg.get("hashtags", [])
        tags_str = " ".join(tags)
        promo_text = plat_cfg.get("promo_text", "")
        promo_link = plat_cfg.get("promo_link", "")

        if platform == "shorts":
            if promo_link and promo_text:
                desc = (
                    f"{title}\n\n"
                    f"💎 {promo_text}\n"
                    f"👉 {promo_link}\n\n"
                    f"🔔 Подпишись на канал, чтобы не пропустить новинки кино!\n\n"
                    f"{tags_str}"
                )
            else:
                desc = (
                    f"{title}\n\n"
                    f"🎬 Название фильма и обсуждение в комментариях!\n"
                    f"🔔 Подпишись на канал, чтобы не пропустить лучшие моменты из кино.\n\n"
                    f"{tags_str}"
                )
            short_title = f"{title} 😱" if not title.endswith("😱") else title
            if len(short_title) > 95:
                short_title = short_title[:92] + "..."
            return {"title": short_title, "description": desc, "hashtags": tags_str}

        elif platform == "tiktok":
            if promo_link:
                caption = f"{title} 🤯 | Ссылка в описании профиля! ⚡ {tags_str}"
            else:
                caption = f"{title} 🎬 Напиши в комментариях, как тебе момент! 👇 {tags_str}"
            return {"title": title, "description": caption, "hashtags": tags_str}

        elif platform == "reels":
            if promo_link and promo_text:
                desc = (
                    f"{title}\n\n"
                    f"⚡ {promo_text}\n"
                    f"👉 Ссылка в шапке профиля: {promo_link}\n\n"
                    f"Ставь лайк и сохраняй, чтобы не потерять!\n\n"
                    f"{tags_str}"
                )
            else:
                desc = (
                    f"{title}\n\n"
                    f"🎬 Оцени момент от 1 до 10 в комментариях!\n"
                    f"Ставь лайк и сохраняй, чтобы не потерять подборку.\n\n"
                    f"{tags_str}"
                )
            return {"title": title, "description": desc, "hashtags": tags_str}

        return {"title": title, "description": "", "hashtags": tags_str}

    def process_clip(
        self,
        input_video: str,
        clip_id: str,
        start_time: str,
        end_time: Optional[str] = None,
        duration: Optional[float] = None,
        hook_title: str = "",
        movie_title: str = "",
        movie_code: str = "",
        subtitles_path: Optional[str] = None,
        target_platforms: Optional[List[str]] = None,
        custom_cta_texts: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Processes a single movie moment and outputs videos with moving video banners for all requested platforms.
        """
        if target_platforms is None:
            target_platforms = ["shorts", "tiktok", "reels"]

        custom_cta_texts = custom_cta_texts or {}
        hwaccel = self.config.get("use_hardware_accel", False)
        norm_audio = self.config.get("normalize_audio", True)

        # Generate millisecond-precise AI subtitles with Whisper directly from the video's audio track!
        ass_sub_path = os.path.join(self.temp_dir, f"{clip_id}_subs.ass")
        ai_subs = self.sub_styler.generate_ai_subtitles(
            video_path=input_video,
            ass_path=ass_sub_path,
            start_time=start_time,
            duration=duration,
            end_time=end_time,
            reference_srt_path=subtitles_path,
            movie_title=movie_title,
            hook_title=hook_title,
        )
        if not ai_subs:
            # Fallback to SRT if Whisper is unavailable
            if subtitles_path and os.path.exists(subtitles_path):
                if subtitles_path.lower().endswith(".srt"):
                    self.sub_styler.convert_srt_to_ass(
                        srt_path=subtitles_path,
                        ass_path=ass_sub_path,
                        start_time=start_time,
                        duration=duration,
                        end_time=end_time,
                    )
                elif subtitles_path.lower().endswith(".ass"):
                    ass_sub_path = subtitles_path
            else:
                ass_sub_path = None

        clip_results = {
            "clip_id": clip_id,
            "movie_title": movie_title,
            "movie_code": movie_code,
            "hook_title": hook_title,
            "input_video": input_video,
            "ass_path": ass_sub_path,
            "start_time": start_time,
            "duration": duration,
            "platforms": {}
        }

        # Bulletproof Windows path: use clean_clip_id directly to avoid WinError 3
        clean_clip_id = re.sub(r'[^\w\-]', '_', clip_id).strip('_')
        clip_out_dir = os.path.join(self.output_base, clean_clip_id)
        os.makedirs(clip_out_dir, exist_ok=True)

        for plat in target_platforms:
            plat_cfg = self.config.get("platforms", {}).get(plat, {})
            if not plat_cfg.get("enabled", True):
                continue

            sponsor_brand = plat_cfg.get("sponsor")
            sponsor_label = sponsor_brand.upper() if sponsor_brand else "ОРГАНИКА (БЕЗ РЕКЛАМЫ)"
            print(f"\n--- [Платформа: {plat.upper()} | Спонсор: {sponsor_label}] Подготовка рендеринга ---")

            # 1. Pick official animated moving video banner (.mov with alpha) only if sponsor is explicitly set
            banner_video = None
            if sponsor_brand in ["funpay", "playerok"]:
                if sponsor_brand == "funpay":
                    cand_v = "assets/banners/funpay/ClipHub_games.mov"
                elif plat == "tiktok":
                    cand_v = "assets/banners/playerok/tiktok1.mov"
                elif plat == "reels":
                    cand_v = "assets/banners/playerok/instagram1.mov"
                else:
                    cand_v = "assets/banners/playerok/shorts1.mov"

                # Check existence or fallbacks
                if not os.path.exists(cand_v):
                    cand_v = "assets/banners/playerok/banner1.mov"

                if os.path.exists(cand_v):
                    banner_video = cand_v
                    print(f"🎥 Используется движущийся спонсорский баннер: {cand_v}")
                else:
                    alt_v = cand_v.replace(".mov", ".mp4")
                    if os.path.exists(alt_v):
                        banner_video = alt_v
                        print(f"🎥 Используется спонсорский видео-баннер: {alt_v}")
            else:
                print(f"🎬 Чистый органический кино-режим для {plat.upper()}: без сторонней рекламы, ссылок и баннеров.")

            # 2. Render Final Video (Clean: only video, subtitles, and moving banner)
            out_video_name = f"{clip_id}_{plat}.mp4"
            out_video_path = os.path.join(clip_out_dir, out_video_name)

            success = self.video_proc.render_vertical_clip(
                input_video=input_video,
                output_video=out_video_path,
                overlay_video=banner_video,
                start_time=start_time,
                end_time=end_time,
                duration=duration,
                subtitles_ass_path=ass_sub_path,
                normalize_audio=norm_audio,
                use_hardware_accel=hwaccel,
            )

            # 3. Generate Metadata (Clean, no codes)
            metadata = self.generate_metadata(plat, hook_title, movie_title, movie_code)
            meta_path = os.path.join(clip_out_dir, f"{clip_id}_{plat}_metadata.txt")
            with open(meta_path, "w", encoding="utf-8") as mf:
                mf.write(f"=== ЗАГОЛОВОК ({plat.upper()}) ===\n{metadata['title']}\n\n")
                mf.write(f"=== ОПИСАНИЕ И ТЕГИ ===\n{metadata['description']}\n")

            if success:
                clip_results["platforms"][plat] = {
                    "video_path": out_video_path,
                    "metadata_path": meta_path,
                    "metadata": metadata,
                }

        # Save summary JSON for this clip
        summary_path = os.path.join(clip_out_dir, "clip_summary.json")
        with open(summary_path, "w", encoding="utf-8") as sf:
            json.dump(clip_results, sf, ensure_ascii=False, indent=2)

        print(f"\n🎉 Клип '{clip_id}' готов для всех платформ в папке: {clip_out_dir}")
        return clip_results

    def re_render_clip(
        self,
        clip_id: str,
        new_ass_path: Optional[str] = None,
        target_platforms: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Quickly re-renders vertical clips using an existing or updated ASS subtitle file.
        Avoids re-downloading or re-transcribing, taking only ~3-5 seconds.
        """
        clean_clip_id = re.sub(r'[^\w\-]', '_', clip_id).strip('_')
        clip_out_dir = os.path.join(self.output_base, clean_clip_id)
        summary_path = os.path.join(clip_out_dir, "clip_summary.json")

        summary_data = {}
        if os.path.exists(summary_path):
            try:
                with open(summary_path, "r", encoding="utf-8") as sf:
                    summary_data = json.load(sf)
            except Exception:
                pass

        input_video = summary_data.get("input_video")
        if not input_video or not os.path.exists(input_video):
            for cand in [
                os.path.join(self.temp_dir, f"{clip_id}.mp4"),
                os.path.join("temp_downloads", f"{clip_id}.mp4"),
                os.path.join("temp_downloads", f"{clip_id.replace('auto_', '')}.mp4"),
            ]:
                if os.path.exists(cand):
                    input_video = cand
                    break

        ass_path = new_ass_path or summary_data.get("ass_path") or os.path.join(self.temp_dir, f"{clip_id}_subs.ass")
        movie_title = summary_data.get("movie_title", "")
        movie_code = summary_data.get("movie_code", "777")
        hook_title = summary_data.get("hook_title", "")
        start_time = summary_data.get("start_time", "00:00:00")
        duration = summary_data.get("duration")

        # Fallback duration detection from ASS subtitles to prevent runaway rendering of full 3-5 min raw videos
        if not duration and ass_path and os.path.exists(ass_path):
            try:
                from subtitle_styler import parse_time_to_seconds
                last_e = 0.0
                with open(ass_path, "r", encoding="utf-8", errors="replace") as af:
                    for l in af:
                        if l.startswith("Dialogue:"):
                            p = l.split(",", 3)
                            if len(p) >= 3:
                                e_val = parse_time_to_seconds(p[2].strip())
                                if e_val > last_e:
                                    last_e = e_val
                if last_e > 5.0:
                    duration = min(58.0, round(last_e + 1.0, 1))
            except Exception:
                pass
        if not duration:
            duration = 58.0

        if target_platforms is None:
            target_platforms = ["shorts", "tiktok"]

        hwaccel = self.config.get("use_hardware_accel", False)
        norm_audio = self.config.get("normalize_audio", True)

        re_results = {
            "clip_id": clip_id,
            "movie_title": movie_title,
            "movie_code": movie_code,
            "hook_title": hook_title,
            "input_video": input_video,
            "ass_path": ass_path,
            "platforms": {}
        }

        for plat in target_platforms:
            plat_cfg = self.config.get("platforms", {}).get(plat, {})
            if not plat_cfg.get("enabled", True):
                continue

            sponsor_brand = plat_cfg.get("sponsor")
            banner_video = None
            if sponsor_brand in ["funpay", "playerok"]:
                if sponsor_brand == "funpay":
                    cand_v = "assets/banners/funpay/ClipHub_games.mov"
                elif plat == "tiktok":
                    cand_v = "assets/banners/playerok/tiktok1.mov"
                elif plat == "reels":
                    cand_v = "assets/banners/playerok/instagram1.mov"
                else:
                    cand_v = "assets/banners/playerok/shorts1.mov"

                if not os.path.exists(cand_v):
                    cand_v = "assets/banners/playerok/banner1.mov"
                if os.path.exists(cand_v):
                    banner_video = cand_v

            out_video_name = f"{clip_id}_{plat}.mp4"
            out_video_path = os.path.join(clip_out_dir, out_video_name)

            success = self.video_proc.render_vertical_clip(
                input_video=input_video,
                output_video=out_video_path,
                overlay_video=banner_video,
                start_time=start_time,
                duration=duration,
                subtitles_ass_path=ass_path,
                normalize_audio=norm_audio,
                use_hardware_accel=hwaccel,
            )

            metadata = self.generate_metadata(plat, hook_title, movie_title, movie_code)
            meta_path = os.path.join(clip_out_dir, f"{clip_id}_{plat}_metadata.txt")
            with open(meta_path, "w", encoding="utf-8") as mf:
                mf.write(f"=== ЗАГОЛОВОК ({plat.upper()}) ===\n{metadata['title']}\n\n")
                mf.write(f"=== ОПИСАНИЕ И ТЕГИ ===\n{metadata['description']}\n")

            if success:
                re_results["platforms"][plat] = {
                    "video_path": out_video_path,
                    "metadata_path": meta_path,
                    "metadata": metadata,
                }

        with open(summary_path, "w", encoding="utf-8") as sf:
            json.dump(re_results, sf, ensure_ascii=False, indent=2)

        return re_results

    def process_batch_file(self, batch_json_path: str):
        """Processes a list of clips defined in a JSON file."""
        if not os.path.exists(batch_json_path):
            raise FileNotFoundError(f"Batch file not found: {batch_json_path}")

        with open(batch_json_path, "r", encoding="utf-8") as f:
            batch_data = json.load(f)

        movie_file = batch_data.get("movie_file")
        movie_title = batch_data.get("movie_title", "Movie")
        clips = batch_data.get("clips", [])

        print(f"🎬 Запуск пакетной обработки: {len(clips)} моментов из '{movie_title}'")
        for i, clip in enumerate(clips, 1):
            clip_id = clip.get("id", f"clip_{i:02d}")
            print(f"\n[{i}/{len(clips)}] Обработка: {clip_id}")
            self.process_clip(
                input_video=movie_file,
                clip_id=clip_id,
                start_time=clip.get("start"),
                end_time=clip.get("end"),
                duration=clip.get("duration"),
                hook_title=clip.get("hook", ""),
                movie_title=movie_title,
                movie_code=clip.get("code", str(i + 100)),
                target_platforms=clip.get("platforms", ["shorts", "tiktok", "reels"]),
                custom_cta_texts=clip.get("custom_ctas"),
            )
