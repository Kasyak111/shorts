"""
Persistent History & Published Tracking Manager.
Tracks which clips and competitor videos have already been published by the creator,
ensuring they are never suggested, searched, or downloaded again.
"""

import os
import sys
import json
import time
from typing import List, Dict, Any, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_HISTORY_FILE = "published_history.json"

class HistoryManager:
    def __init__(self, file_path: str = DEFAULT_HISTORY_FILE):
        self.file_path = os.path.abspath(file_path)
        self.data: Dict[str, Any] = {"published_ids": [], "items": {}}
        self._load()

    def _load(self):
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8-sig") as f:
                    content = f.read().strip()
                    if content:
                        self.data = json.loads(content)
                    else:
                        self.data = {"published_ids": [], "items": {}}
            except Exception as e:
                print(f"⚠️ Ошибка чтения истории публикаций: {e}")
                self.data = {"published_ids": [], "items": {}}
        else:
            self.data = {"published_ids": [], "items": {}}

    def _save(self):
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ Ошибка сохранения истории публикаций: {e}")

    def is_published(self, video_id: Optional[str] = None, url: Optional[str] = None) -> bool:
        """Checks if video ID or URL has already been marked as published."""
        if not video_id and not url:
            return False

        pub_ids = set(self.data.get("published_ids", []))

        if video_id:
            clean_id = str(video_id).strip()
            if clean_id in pub_ids:
                return True

        if url:
            clean_url = str(url).strip()
            # 1. Check if any published video ID is contained in the URL
            for pid in pub_ids:
                if pid and pid in clean_url:
                    return True

            # 2. Check stored items URLs
            clean_url_lower = clean_url.lower()
            for vid, meta in self.data.get("items", {}).items():
                m_url = str(meta.get("url", "")).strip().lower()
                if m_url and (clean_url_lower in m_url or m_url in clean_url_lower):
                    return True
        return False

    def mark_published(self, video_id: str, title: str = "", url: str = "") -> bool:
        """Marks a video as published so it will never be retrieved again."""
        if not video_id:
            return False

        clean_id = str(video_id).strip()
        pub_ids = self.data.setdefault("published_ids", [])
        if clean_id not in pub_ids:
            pub_ids.append(clean_id)

        items = self.data.setdefault("items", {})
        items[clean_id] = {
            "title": title or f"Movie_{clean_id}",
            "url": url or "",
            "published_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._save()
        print(f"✅ Ролик '{clean_id}' успешно добавлен в список опубликованных!")
        return True

    def unmark_published(self, video_id: str) -> bool:
        """Removes a video from published list (undo)."""
        if not video_id:
            return False

        clean_id = str(video_id).strip()
        pub_ids = self.data.setdefault("published_ids", [])
        if clean_id in pub_ids:
            pub_ids.remove(clean_id)

        items = self.data.setdefault("items", {})
        if clean_id in items:
            del items[clean_id]

        self._save()
        print(f"↩️ Ролик '{clean_id}' убран из списка опубликованных!")
        return True

    def get_published_list(self) -> List[Dict[str, Any]]:
        """Returns all published items with metadata."""
        res = []
        for vid in self.data.get("published_ids", []):
            item = self.data.get("items", {}).get(vid, {})
            res.append({
                "id": vid,
                "title": item.get("title", f"Clip {vid}"),
                "url": item.get("url", ""),
                "published_at": item.get("published_at", "Неизвестно"),
            })
        return res

    def get_published_count(self) -> int:
        return len(self.data.get("published_ids", []))
