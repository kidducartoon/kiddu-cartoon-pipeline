"""
Publish Engine — Stage 5.

Uploads the final video to YouTube with keyword-optimized metadata for Hindi kids'
cartoon discovery.

NOTE on storage: the original design used a Google Drive buffer as short-term storage
between rendering and publishing. That's been removed -- Google Drive service accounts
cannot own/create files in a regular personal Drive (confirmed via a real failed upload:
"Service Accounts do not have storage quota... use OAuth delegation or shared drives"),
and Shared Drives require Google Workspace, which this $0 personal-account setup doesn't
have. It's also unnecessary: GitHub Actions already holds the rendered video locally on
the runner for the full duration of a single job run, uploads it directly to YouTube from
there, and the runner (and every local file on it) is destroyed when the job ends. That
achieves the same "no permanent storage of raw video files" goal without needing Drive
at all.

Required secrets (GitHub Actions repo secrets):
  YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN
      -- OAuth2 credentials for the channel's own Google account (YouTube Data API v3,
         scope: https://www.googleapis.com/auth/youtube.upload)
"""
import os
from pathlib import Path
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

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
        try:
            youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(thumbnail_path))).execute()
        except Exception as e:
            # Known limitation: custom thumbnails require phone-verifying the channel.
            # Confirmed via a real failed manual upload (403: "doesn't have permissions
            # to upload and set custom video thumbnails"). Not fatal -- YouTube still
            # auto-generates a thumbnail from the video itself, so don't fail the whole
            # publish over this.
            print(f"[publish_engine] thumbnail set failed (non-fatal): {e}")

    return video_id


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


def publish_job(job_id: str, final_video_path: Path, thumbnail_path: Path, script: dict) -> dict:
    tags = build_seo_tags(script["youtube_tags"])
    video_id = upload_to_youtube(
        video_path=final_video_path,
        thumbnail_path=thumbnail_path,
        title=script["title"],
        description=script["youtube_description"],
        tags=tags,
    )
    return {"youtube_video_id": video_id, "youtube_url": f"https://youtu.be/{video_id}"}
