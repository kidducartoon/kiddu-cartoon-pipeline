"""
Publish Engine — Stage 5.

Uploads the final video to YouTube with keyword-optimized metadata for Hindi kids'
cartoon discovery, then deletes the corresponding buffered file from Google Drive to
save space (ONLY after upload is confirmed successful -- crash-proofing rule: never
delete the only copy of a video before its replacement/destination is confirmed).

Required secrets (GitHub Actions repo secrets):
  YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN
      -- OAuth2 credentials for the channel's own Google account (YouTube Data API v3,
         scope: https://www.googleapis.com/auth/youtube.upload)
  GDRIVE_SERVICE_ACCOUNT_JSON
      -- a Google service account JSON (base64-encoded) with access to the Drive buffer folder
  GDRIVE_BUFFER_FOLDER_ID
      -- the Drive folder ID used as short-term video storage before upload
"""
import os
import json
import base64
import requests
from pathlib import Path
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2 import service_account
from googleapiclient.discovery import build as gbuild

CATEGORY_ID_FILM_ANIMATION = "1"  # YouTube category: Film & Animation... using "24" Entertainment
                                   # is also common for kids' channels; keep configurable.


def get_youtube_client():
    creds = Credentials(
        None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
    )
    return build("youtube", "v3", credentials=creds)


def upload_to_youtube(video_path: Path, thumbnail_path: Path, title: str, description: str,
                       tags: list[str], made_for_kids: bool = True) -> str:
    youtube = get_youtube_client()
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags[:500],
            "categoryId": CATEGORY_ID_FILM_ANIMATION,
            "defaultLanguage": "hi",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": made_for_kids,
        },
    }
    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
    video_id = response["id"]

    if thumbnail_path and thumbnail_path.exists():
        youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(thumbnail_path))).execute()

    return video_id


def get_drive_client():
    sa_json = base64.b64decode(os.environ["GDRIVE_SERVICE_ACCOUNT_JSON"]).decode()
    info = json.loads(sa_json)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive"]
    )
    return gbuild("drive", "v3", credentials=creds)


def upload_to_drive_buffer(local_path: Path, filename: str) -> str:
    """Upload a rendered video to the Drive buffer folder; returns the Drive file ID.
    Used as short-term storage between rendering and publishing, per the requested design."""
    drive = get_drive_client()
    folder_id = os.environ["GDRIVE_BUFFER_FOLDER_ID"]
    file_metadata = {"name": filename, "parents": [folder_id]}
    from googleapiclient.http import MediaFileUpload as DriveMediaUpload
    media = DriveMediaUpload(str(local_path), resumable=True)
    file = drive.files().create(body=file_metadata, media_body=media, fields="id").execute()
    return file["id"]


def delete_from_drive_buffer(drive_file_id: str):
    """ONLY call this after upload_to_youtube has returned a confirmed video_id."""
    drive = get_drive_client()
    drive.files().delete(fileId=drive_file_id).execute()


def build_seo_tags(base_tags: list[str]) -> list[str]:
    """Append a standard set of high-traffic Hindi-kids-cartoon discovery tags on top of
    the script's own tags, deduplicated, so every video benefits from consistent
    channel-level keyword coverage in addition to its unique topic tags."""
    evergreen_tags = [
        "hindi kids song", "bacchon ke geet", "hindi cartoon", "hindi rhymes",
        "kids cartoon hindi", "moral stories hindi", "hindi nursery rhymes",
        "cartoon for kids", "hindi kahani", "animated hindi song", "kiddu cartoon",
        "bachon ka gana", "hindi balgeet",
    ]
    seen = set()
    combined = []
    for t in base_tags + evergreen_tags:
        key = t.strip().lower()
        if key and key not in seen:
            seen.add(key)
            combined.append(t.strip())
    return combined


def publish_job(job_id: str, final_video_path: Path, thumbnail_path: Path, script: dict,
                 drive_file_id: str = None) -> dict:
    tags = build_seo_tags(script["youtube_tags"])
    video_id = upload_to_youtube(
        video_path=final_video_path,
        thumbnail_path=thumbnail_path,
        title=script["title"],
        description=script["youtube_description"],
        tags=tags,
    )
    if drive_file_id:
        delete_from_drive_buffer(drive_file_id)
    return {"youtube_video_id": video_id, "youtube_url": f"https://youtu.be/{video_id}"}
