"""
Script Engine — Stage 1.

1. Uses YouTube Data API (search.list) to find top Hindi kids'-song videos right now
   (Gemini itself cannot browse YouTube -- this is a real API call, not model guessing).
2. Feeds those titles/descriptions as trend context into Gemini, asking for a brand-new,
   ORIGINAL structured song script (never copying any fetched video's lyrics/plot --
   only using them as a topic/trend signal, to respect copyright and avoid duplicate
   content strikes on the channel).
3. Output is strict JSON: title, mood, lyrics_lines[], scenes[], tags[], description.

Required secrets (set as GitHub Actions repo secrets):
  YOUTUBE_API_KEY   - YouTube Data API v3 key (free tier, Google Cloud Console)
  GEMINI_API_KEY    - Google AI Studio / Gemini API key (free tier)
"""
import os
import json
import requests

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.0-flash"  # fast + free-tier friendly; swap via env if needed
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"


def fetch_trending_hindi_kids_songs(max_results: int = 10) -> list[dict]:
    if not YOUTUBE_API_KEY:
        raise RuntimeError("YOUTUBE_API_KEY not set")
    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/search",
        params={
            "key": YOUTUBE_API_KEY,
            "part": "snippet",
            "q": "hindi kids song cartoon bacchon ka geet",
            "type": "video",
            "order": "viewCount",
            "relevanceLanguage": "hi",
            "regionCode": "IN",
            "maxResults": max_results,
        },
        timeout=20,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    return [
        {
            "title": it["snippet"]["title"],
            "description": it["snippet"]["description"][:200],
            "channel": it["snippet"]["channelTitle"],
        }
        for it in items
    ]


SCRIPT_PROMPT_TEMPLATE = """You are a professional children's song writer for a Hindi-language
YouTube channel making Pixar-style stylized 3D-look musical cartoon videos for kids (ages 2-8).

Here are the titles/topics of currently popular Hindi kids' song videos on YouTube, for TREND
CONTEXT ONLY. Do NOT copy, adapt, or paraphrase any of their lyrics or story -- only use them to
understand what topics/themes are currently popular, then write something ENTIRELY ORIGINAL:

{trend_context}

Write ONE original Hindi children's song with these hard requirements:
- Simple, rhythmic, rhyming Hindi lyrics suitable for a 2-8 year old audience
- Positive, wholesome, educational or joyful theme (friendship, sharing, nature, counting,
  animals, good habits, festivals, family) -- NOTHING scary, violent, or inappropriate
- {n_lines} short lyric lines, each independently singable (roughly 4-8 words)
- A consistent single main character (name, appearance, personality) reused across the song
- A consistent background/setting theme
- One camera movement suggestion per lyric line (pan-left, pan-right, zoom-in, zoom-out, static)

Respond with ONLY valid JSON, no markdown fences, no preamble, matching exactly this schema:
{{
  "title": "string (Hindi, catchy, under 60 chars)",
  "title_english_transliteration": "string",
  "mood": "one of: happy, playful, calm, lullaby",
  "character": {{"name": "string", "appearance": "string, detailed visual description for image generation", "personality": "string"}},
  "background_setting": "string, detailed visual description for image generation",
  "lyrics_lines": ["line1 in Hindi (Devanagari script)", "line2", "..."],
  "scenes": [
    {{"line_index": 0, "scene_description": "string, what's happening visually", "camera_move": "pan-left|pan-right|zoom-in|zoom-out|static"}}
  ],
  "youtube_tags": ["10-15 relevant Hindi + English keyword tags for kids/cartoon/hindi song discovery"],
  "youtube_description": "string, 2-3 sentences, keyword-rich, mentions it's an original animated Hindi kids song"
}}
"""


def call_gemini(prompt: str) -> dict:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set")
    resp = requests.post(
        f"{GEMINI_URL}?key={GEMINI_API_KEY}",
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.9, "responseMimeType": "application/json"},
        },
        timeout=60,
    )
    resp.raise_for_status()
    text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


def generate_script(n_lines: int = 6) -> dict:
    """Full Stage-1 pipeline: fetch trends -> build prompt -> call Gemini -> validated JSON."""
    trending = fetch_trending_hindi_kids_songs()
    trend_context = "\n".join(f"- {t['title']} (channel: {t['channel']})" for t in trending)
    prompt = SCRIPT_PROMPT_TEMPLATE.format(trend_context=trend_context, n_lines=n_lines)
    script = call_gemini(prompt)

    # basic schema validation -- fail loudly & specifically rather than silently
    # producing a broken downstream job (crash-proofing principle: fail fast, fail clearly)
    required_keys = ["title", "mood", "character", "background_setting", "lyrics_lines",
                      "scenes", "youtube_tags", "youtube_description"]
    missing = [k for k in required_keys if k not in script]
    if missing:
        raise ValueError(f"Gemini script missing required keys: {missing}")
    if len(script["lyrics_lines"]) < 2:
        raise ValueError("Script has too few lyric lines")
    if script["mood"] not in ("happy", "playful", "calm", "lullaby"):
        script["mood"] = "happy"  # safe fallback rather than failing the whole job

    return script


if __name__ == "__main__":
    print(json.dumps(generate_script(), indent=2, ensure_ascii=False))
