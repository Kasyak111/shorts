"""
LLM-Powered Subtitle Context & Grammar Polisher.
Uses Google Gemini API (or compatible LLMs) to transform raw phonetic Whisper
transcriptions into studio-quality, grammatically perfect, cinema-aware subtitles.
Fixes:
- Character names and movie entities (e.g., 'АХИ ЛЕЗ' -> 'АХИЛЛЕС')
- Case/gender/declension errors (e.g., 'К ЖЁНОМ' -> 'К ЖЁНАМ')
- Removes blogger outro watermarks (e.g., 'С вами был Игорь Негода')
- Eliminates dangling prepositions and unnatural pause punctuation.
"""

import os
import re
import sys
import json
import requests
from typing import List, Dict, Optional, Any

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

class LLMSubtitleCorrector:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gemini-3.8-flash",
        config_path: str = "config.json"
    ):
        self.config_path = config_path
        self.api_key = api_key
        self.model = model
        self.enabled = True

        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f).get("llm", {})
                    if not self.api_key:
                        self.api_key = cfg.get("api_key", "").strip() or os.getenv("GEMINI_API_KEY", "").strip()
                    self.model = cfg.get("model", self.model)
                    self.enabled = cfg.get("enabled", True)
            except Exception:
                pass

    def is_configured(self) -> bool:
        """Returns True if a valid Gemini API key is provided and enabled."""
        return bool(self.enabled and self.api_key and len(self.api_key) > 10)

    def set_api_key(self, key: str) -> bool:
        """Saves API key to config.json and memory."""
        self.api_key = key.strip()
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if "llm" not in data:
                    data["llm"] = {}
                data["llm"]["api_key"] = self.api_key
                data["llm"]["enabled"] = True
                with open(self.config_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                return True
            except Exception as e:
                print(f"⚠️ Ошибка сохранения API-ключа в config.json: {e}")
        return False

    def _offline_fallback(self, raw_phrases: List[str]) -> List[str]:
        """
        Offline rule-based fallback when Gemini API is unavailable, disabled, or rate-limited.
        Cleans blogger promotional voiceovers (replacing with ""), vocatives, phonetics, and grammar.
        """
        try:
            from grammar_corrector import RussianGrammarCorrector
            corrector = RussianGrammarCorrector()
        except Exception as e:
            print(f"⚠️ Ошибка загрузки офлайн-корректора грамматики: {e}", flush=True)
            return raw_phrases

        polished = []
        for phrase in raw_phrases:
            if not phrase or not phrase.strip():
                polished.append("")
                continue

            # Clean and correct phonetics, vocatives, agreements, and strip attached promos
            try:
                cleaned = corrector.clean_and_correct(phrase, is_subtitle_chunk=True)
            except Exception as ex:
                print(f"⚠️ Ошибка офлайн-коррекции фразы '{phrase}': {ex}", flush=True)
                cleaned = phrase

            # If promo stripping reduced phrase to empty string
            if not cleaned or not cleaned.strip():
                if hasattr(corrector, "is_blogger_promo") and corrector.is_blogger_promo(phrase):
                    print(f"🧹 [Офлайн-корректор] Удалена реклама блогера: '{phrase}'", flush=True)
                polished.append("")
            else:
                polished.append(cleaned)

        return polished

    def polish_cues(
        self,
        raw_phrases: List[str],
        movie_title: str = "",
        hook_title: str = ""
    ) -> List[str]:
        """
        Sends raw phonetic Whisper phrases to Google Gemini for contextual cinema editing.
        Returns a list of equal length where each phrase is polished.
        """
        if not raw_phrases:
            return []

        if not self.is_configured():
            print("ℹ️ LLM-корректор выключен или API-ключ Gemini не задан. Используется офлайн-корректор.", flush=True)
            return self._offline_fallback(raw_phrases)

        context_info = f"Фильм: «{movie_title}»." if movie_title else "Контекст: популярный фильм / кинофильм."
        if hook_title:
            context_info += f" Тема сцены: «{hook_title}»."
        input_items = [{"id": i, "text": p} for i, p in enumerate(raw_phrases)]

        prompt = f"""Ты — главный редактор студийных субтитров к кинофильмам для вертикальных роликов (Shorts/TikTok/Reels).
Твоя задача — исправить сырую транскрипцию нейросети (Whisper AI), сделав реплики безупречно грамотными, кинематографичными и точно соответствующими дубляжу.

{context_info}

СТРОЖАЙШЕЕ ПРАВИЛО СИНХРОНИЗАЦИИ (КРИТИЧЕСКИ ВАЖНО):
Каждый входной объект {{"id": N, "text": "..."}} жестко привязан к миллисекундному таймкоду на видео.
Для каждого входного объекта верни ровно один объект с тем же "id": N и исправленным "text".
КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО:
- Объединять несколько id в один
- Разделять один id на несколько
- Удалять id или менять их порядок
- Менять количество элементов: на выходе должно быть ровно {len(raw_phrases)} элементов с id от 0 до {len(raw_phrases) - 1}!

СТРОГИЕ ПРАВИЛА ОБРАБОТКИ:
1. 0 ФОНЕТИЧЕСКИХ ИСКАЖЕНИЙ В ДИАЛОГАХ: Исправь все фонетические ошибки распознавания и слуховые ослышки Whisper в кино (например: «СЕМЬ НАЗАД» -> «ВСЕМ НАЗАД», «БОССА» при обращении бойца к командиру -> «БОСС», «АХИ ЛЕЗ» -> «АХИЛЛЕС», «ДЕДШОТ» -> «ДЭДШОТ», «ГРИГС» -> «ГРИГГС»). Восстанови точный логичный дубляж фильма.
2. ИСПРАВЛЕНИЕ ГРАММАТИКИ: Исправь падежи, склонения, род и окончания слов (например: «ДОМОЙ К ЖЁНОМ» -> «ДОМОЙ К ЖЁНАМ», «У ТЕБЯ ОДНО ОБОЙМА» -> «У ТЕБЯ ОДНА ОБОЙМА», «ПЕРВЫЙ ВСТРЕЧА» -> «ПЕРВАЯ ВСТРЕЧА», «ЭТИМ ПОДОНКАМИ» -> «ЭТИМИ ПОДОНКАМИ»).
3. ПОЛНОЕ УДАЛЕНИЕ РЕКЛАМЫ БЛОГЕРОВ: Любые чужие рекламные вставки блогеров, каналов и водяные знаки (например: «С вами был...», «Подпишись», «Подписывайтесь», «Ставьте лайк», «Код в закрепе», «Ссылка в описании», «Русский дубляж», «Художественный фильм») СТРОГО ЗАМЕНЯЙ НА ПУСТУЮ СТРОКУ "" в поле "text" (сохраняя тот же id!). 0 рекламных вставок блогеров на экране!
4. СОХРАНЕНИЕ ДИАЛОГОВ КИНО: Реплики персонажей кино (даже короткие фразы вроде «Что на обед?», «Тише!», «Готово», «Стой!») НИ В КОЕМ СЛУЧАЕ НЕ УДАЛЯЙ!
5. ОБРАЩЕНИЯ В ИМЕНИТЕЛЬНОМ ПАДЕЖЕ: Все обращения к персонажам («босс», «командир», «шеф», «майор», «капитан», «сержант») строго оформляй в ИМЕНИТЕЛЬНОМ ПАДЕЖЕ обращения с правильной пунктуацией (например: «БОСС, МЫ ГОТОВЫ», «ОДНО СЛОВО, БОСС, И Я УЛОЖУ ЕГО», а НЕ «босса»).
6. УБЕРИ ВИСЯЧИЕ ПРЕДЛОГИ: Никаких висячих предлогов и союзов («С», «В», «К», «О», «НА», «ЗА») на конце строк.

ВХОДНЫЕ ДАННЫЕ (список сырых фраз с жесткой привязкой к id):
{json.dumps(input_items, ensure_ascii=False, indent=2)}

ФОРМАТ ОТВЕТА (только валидный JSON, без лишнего markdown):
{{"corrected": [
  {{"id": 0, "text": "исправленный текст 0"}},
  {{"id": 1, "text": "исправленный текст 1"}},
  ...
]}}"""

        # Multi-model cascade loop: gemini-3.5-flash-lite -> gemini-flash-latest -> gemini-2.5-flash -> offline fallback
        base_models = [
            self.model,
            "gemini-3.5-flash-lite",
            "gemini-flash-latest",
            "gemini-2.5-flash",
        ]
        models_to_try = []
        for m in base_models:
            if m and m not in models_to_try:
                models_to_try.append(m)

        import time
        for m in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={self.api_key}"
            payload = {
                "contents": [
                    {
                        "parts": [{"text": prompt}]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.1,
                    "responseMimeType": "application/json"
                }
            }

            try:
                print(f"✨ Отправка {len(raw_phrases)} фраз в Google Gemini ({m}) для студийной полировки...", flush=True)
                resp = requests.post(url, json=payload, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        text_res = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        clean_json = re.sub(r"^```(?:json)?\s*|\s*```$", "", text_res.strip())
                        parsed = json.loads(clean_json)
                        corrected_list = parsed.get("corrected", [])
                        
                        id_map = {}
                        flat_list = []
                        if isinstance(corrected_list, list):
                            for idx, item in enumerate(corrected_list):
                                if isinstance(item, dict) and "id" in item and "text" in item:
                                    try:
                                        id_map[int(item["id"])] = str(item["text"]).strip()
                                    except (ValueError, TypeError):
                                        pass
                                elif isinstance(item, str):
                                    flat_list.append(item.strip())

                        if id_map:
                            res = []
                            for idx, raw in enumerate(raw_phrases):
                                if idx in id_map:
                                    res.append(id_map[idx])
                                else:
                                    res.append(raw)
                            print(f"✅ Gemini ({m}) успешно отполировал {len(res)} реплик с точной синхронизацией 1-к-1!", flush=True)
                            return res
                        elif len(flat_list) == len(raw_phrases):
                            print(f"✅ Gemini ({m}) успешно отполировал {len(flat_list)} реплик с кино-контекстом!", flush=True)
                            return flat_list
                        elif flat_list:
                            print(f"⚠️ Длина ответа Gemini ({len(flat_list)}) отличается от входа ({len(raw_phrases)}). Выполняем согласование...", flush=True)
                            res = []
                            for i in range(len(raw_phrases)):
                                if i < len(flat_list):
                                    res.append(flat_list[i])
                                else:
                                    res.append(raw_phrases[i])
                            return res
                elif resp.status_code in [503, 429]:
                    print(f"⚠️ Модель {m} перегружена (статус {resp.status_code}). Мгновенный переход к следующей быстрой модели...", flush=True)
                    time.sleep(1.0)
                else:
                    err_msg = resp.text[:200]
                    print(f"⚠️ Gemini API ({m}) вернул статус {resp.status_code}: {err_msg}", flush=True)
            except Exception as ex:
                print(f"⚠️ Ошибка вызова Gemini ({m}): {ex}", flush=True)

        print("❌ ВНИМАНИЕ: Все модели Gemini временно недоступны. Откат к локальной грамматике.", flush=True)
        return self._offline_fallback(raw_phrases)
