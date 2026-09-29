"""
YouTube Shorts Direct Uploader.
Uploads rendered vertical clips directly to YouTube channel using official YouTube Data API v3.
Requires credentials from Google Cloud Console (client_secrets.json).
"""

import os
import sys
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request
import pickle

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def get_authenticated_service(client_secrets_file: str = "client_secret.json"):
    credentials = None
    token_file = "token_youtube.pickle"

    if os.path.exists(token_file):
        with open(token_file, "rb") as token:
            credentials = pickle.load(token)

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            if not os.path.exists(client_secrets_file):
                raise FileNotFoundError(
                    f"Файл '{client_secrets_file}' не найден. "
                    "Скачайте OAuth 2.0 Client ID JSON из Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(client_secrets_file, SCOPES)
            credentials = flow.run_local_server(port=0)

        with open(token_file, "wb") as token:
            pickle.dump(credentials, token)

    return build("youtube", "v3", credentials=credentials)

def upload_short(
    video_path: str,
    title: str,
    description: str,
    tags: list[str] = None,
    privacy_status: str = "public", # "public", "private", "unlisted"
    client_secrets_file: str = "client_secret.json"
):
    """Uploads a video to YouTube Shorts."""
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")

    youtube = get_authenticated_service(client_secrets_file)

    # Ensure title contains #Shorts for YouTube algorithm detection
    if "#shorts" not in title.lower() and "#short" not in title.lower():
        title = f"{title} #Shorts"

    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags or ["Shorts", "кино", "фильмы"],
            "categoryId": "1" # Film & Animation
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False
        }
    }

    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        media_body=media
    )

    print(f"🚀 Загрузка видео '{os.path.basename(video_path)}' на YouTube Shorts...")
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  Загружено {int(status.progress() * 100)}%...")

    video_id = response.get("id")
    print(f"✅ Успешно опубликовано! Ссылка: https://youtube.com/shorts/{video_id}")
    return video_id

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Использование: python youtube_uploader.py <путь_к_видео> <заголовок> [описание]")
        sys.exit(1)
    vid = sys.argv[1]
    tit = sys.argv[2]
    desc = sys.argv[3] if len(sys.argv) > 3 else ""
    upload_short(vid, tit, desc)
