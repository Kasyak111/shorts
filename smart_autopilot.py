"""
Smart Autopilot Module.
Automatically:
1. Spies on competitors (channels or search queries)
2. Discovers viral movie moments with high views
3. Extracts movie title, code, and hook
4. Downloads the viral segment
5. Renders vertical 9:16 videos with:
   - FUNPAY banner for YouTube Shorts
   - PLAYEROK banner for TikTok
   - PLAYEROK banner for Instagram Reels
6. Generates high-converting referral copy
7. Optionally dispatches directly to Telegram
"""

import os
import sys
import json
from typing import List, Optional
from competitor_scanner import CompetitorScanner
from clip_manager import ClipManager

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

class SmartAutopilot:
    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.scanner = CompetitorScanner()
        self.manager = ClipManager(config_path=config_path)
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)

    def run(
        self,
        source: Optional[str] = None,
        count: int = 2,
        min_views: Optional[int] = None,
        platforms: Optional[List[str]] = None,
    ):
        """
        Executes the autonomous spy-and-repurpose loop.
        """
        if platforms is None:
            platforms = ["shorts", "tiktok", "reels"]

        comp_cfg = self.config.get("competitors", {})
        query = source or comp_cfg.get("default_queries", ["отрывок фильм шортс"])[0]
        views_thresh = min_views if min_views is not None else comp_cfg.get("min_views_threshold", 1000)

        print(f"\n=======================================================")
        print(f"🤖 ЗАПУСК АВТОПИЛОТА: ШПИОНАЖ ЗА КОНКУРЕНТАМИ")
        print(f"🎯 Источник/запрос: {query}")
        print(f"💰 Баннеры: FUNPAY (Shorts) + PLAYEROK (TikTok / Reels)")
        print(f"=======================================================\n")

        # 1. Spy on competitors
        trending_clips = self.scanner.search_trending_movie_shorts(
            query_or_channel=query,
            max_results=count,
            min_views=views_thresh
        )

        if not trending_clips:
            print("⚠️ Не найдено роликов по указанным фильтрам. Попробуйте другой запрос или уменьшите порог просмотров.")
            return []

        processed_results = []
        for idx, item in enumerate(trending_clips, 1):
            vid_id = item.get("id")
            title = item.get("title", "")
            webpage_url = item.get("webpage_url") or item.get("url")
            movie_title = item.get("movie_title") or f"Movie_{vid_id}"
            movie_code = item.get("movie_code") or str(idx + 500)
            hook_title = item.get("hook_title") or "ЭТОТ МОМЕНТ СТОИТ УВИДЕТЬ 😱"
            views = item.get("view_count", 0)

            print(f"\n[{idx}/{len(trending_clips)}] 🎬 Вирусный ролик конкурента: '{title}' ({views:,} просмотров)")
            print(f"    🍿 Распознан фильм: {movie_title} | Код: {movie_code}")
            print(f"    🎣 Главный хук: {hook_title}")

            # 2. Download clip and subtitles
            downloaded_video, sub_file = self.scanner.download_clip(
                video_url=webpage_url,
                output_filename=os.path.join(self.manager.temp_dir, f"source_{vid_id}.mp4")
            )

            if not downloaded_video or not os.path.exists(downloaded_video):
                print(f"❌ Пропуск ролика {vid_id} из-за ошибки загрузки.")
                continue

            orig_duration = item.get("duration") or 0

            # 2.5 Speech Quality Gate: ensure candidate has rich, intelligible dialogue
            # (Only perform on automated search; if user gave explicit URL, honor it)
            is_direct_user_url = bool(source and ("watch?v=" in source or "youtu.be/" in source or "/shorts/" in source))
            if not is_direct_user_url:
                print(f"🎙️ Проверка плотности речи (Speech Quality Gate)...", flush=True)
                speech_check = self.manager.sub_styler.validate_speech_quality(
                    video_or_audio_path=downloaded_video,
                    duration=float(orig_duration) if orig_duration else None
                )
                if not speech_check.get("valid", True):
                    reason = speech_check.get("reason", "Мало речи")
                    print(f"⏩ Отклонен кандидат '{title}': {reason}. Поиск следующего вирусного ролика с хорошим диалогом...")
                    try:
                        os.remove(downloaded_video)
                    except Exception:
                        pass
                    continue
                else:
                    print(f"✅ Speech Quality Gate пройден! Слов: {speech_check['words_count']} | Речь: {speech_check['speech_ratio']:.1%} | Пример: «{speech_check['sample_text']}»")

            # 3. Handle duration compliance (FunPay ClipHub requires >= 24 seconds, Shorts max 60s)
            if orig_duration > 60:
                clip_start = "00:00:00"
                clip_dur = 58.0  # Safe <= 60s for Shorts and TikTok
            else:
                clip_start = "00:00:00"
                clip_dur = None

            # 4. Process and render with FunPay and PlayerOk banners + stylish animated subtitles
            clip_res = self.manager.process_clip(
                input_video=downloaded_video,
                clip_id=f"auto_{vid_id}",
                start_time=clip_start,
                duration=clip_dur,
                hook_title=hook_title,
                movie_title=movie_title,
                movie_code=movie_code,
                subtitles_path=sub_file,
                target_platforms=platforms,
            )
            clip_res["source_id"] = vid_id
            clip_res["webpage_url"] = webpage_url
            clip_res["source_title"] = title
            processed_results.append(clip_res)

            if len(processed_results) >= count:
                break

        print("\n=======================================================")
        print(f"🎉 АВТОПИЛОТ ЗАВЕРШИЛ РАБОТУ! Обработано роликов: {len(processed_results)}")
        print(f"📁 Все готовые видео с баннерами FunPay и PlayerOk находятся в:")
        print(f"   {self.manager.output_base}")
        print("=======================================================\n")
        return processed_results

if __name__ == "__main__":
    autopilot = SmartAutopilot()
    autopilot.run(count=1)
