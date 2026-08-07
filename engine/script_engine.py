"""
Script Engine — Stage 1. REWRITTEN to run at $0 without Gemini.

Why: Gemini API access on this Google Cloud org requires OAuth (service-account-bound
keys, forced by org policy) and OAuth-authenticated requests get 0 free-tier quota until
billing is enabled -- which this project explicitly does not want. Rather than block the
whole pipeline on that, scripts are generated locally by randomly combining a bank of
characters / settings / lyric-line templates, deterministically seeded by job_id (so a
crash-recovery re-run produces the identical script, matching the rest of the pipeline's
determinism guarantee).

YouTube trend fetch is kept -- it's real signal, free, and still useful for keyword tags
even without an LLM to read it.
"""
import os
import random
import requests

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")

CHARACTERS = [
    {"name": "Chintu", "appearance": "a cheerful round baby elephant, light blue skin, big floppy ears, small red bow tie, big friendly eyes", "personality": "curious, kind, loves making friends"},
    {"name": "Mithu", "appearance": "a small fluffy yellow chick with a tiny orange beak, red bow on head, round soft body", "personality": "playful, energetic, always singing"},
    {"name": "Bunty", "appearance": "a chubby brown bear cub with a green scarf, round ears, warm smile", "personality": "gentle, sleepy, loves helping others"},
    {"name": "Golu", "appearance": "a spotted baby giraffe with a yellow bandana, long eyelashes, gentle smile", "personality": "shy but curious, loves exploring"},
    {"name": "Pinki", "appearance": "a small pink baby rabbit with long floppy ears, a polka dot bow, twitchy nose", "personality": "bouncy, cheerful, loves to dance"},
]

BACKGROUNDS = [
    "a sunny green meadow with tall trees, colorful flowers, and a small sparkling pond",
    "a cozy village courtyard with mango trees and a small well",
    "a rainbow-colored garden full of butterflies and blooming flowers",
    "a gentle riverside with smooth stones and swaying reeds",
    "a starlit night sky over a quiet hillside with fireflies glowing",
]

THEMES = [
    {
        "mood": "happy",
        "lines": ["{char} चला घूमने बाग में", "फूलों से करे वो बात",
                  "तितली संग वो नाचे गाए", "पानी में करे छपाक",
                  "दोस्तों को वो बुलाए पास", "सब मिलकर मनाएं खास"],
        "scenes": ["{char} walking happily into the setting", "{char} bending down to smell colorful flowers",
                   "{char} dancing with a butterfly fluttering around", "{char} splashing happily in water",
                   "{char} waving and calling friends to join", "{char} and friends all together celebrating"],
        "camera": ["pan-right", "zoom-in", "pan-left", "zoom-out", "static", "zoom-out"],
    },
    {
        "mood": "playful",
        "lines": ["{char} गिने एक दो तीन", "फिर गिने चार पांच छह",
                  "सात आठ नौ फिर दस", "गिनती करे वो बस",
                  "सबको सिखाए गिनना संग", "मस्ती में मने ये रंग"],
        "scenes": ["{char} counting on fingers excitedly", "{char} hopping and counting more",
                   "{char} pointing at things while counting", "{char} finishing the count happily",
                   "{char} teaching friends to count together", "{char} and friends celebrating with colors"],
        "camera": ["zoom-in", "pan-left", "pan-right", "static", "zoom-out", "zoom-out"],
    },
    {
        "mood": "calm",
        "lines": ["{char} सोता चुपचाप रात में", "तारे चमके आसमान में",
                  "चंदा मामा दे रहे प्यार", "नींद में सपनों की बहार",
                  "मम्मी गाए लोरी प्यारी", "सो जाए दुनिया सारी"],
        "scenes": ["{char} lying down peacefully under the stars", "twinkling stars filling the night sky",
                   "the moon glowing softly above", "{char} dreaming happily with a gentle smile",
                   "a warm cozy scene of comfort and love", "the whole scene settling into peaceful sleep"],
        "camera": ["static", "zoom-out", "pan-right", "zoom-in", "static", "zoom-out"],
    },
    {
        "mood": "playful",
        "lines": ["{char} बांटे अपनी मिठाई", "दोस्तों संग खाए भाई",
                  "साथ मिलकर खेले खेल", "मस्ती में हो अच्छा मेल",
                  "एक दूजे की मदद करें", "प्यार से मिलजुल कर रहें"],
        "scenes": ["{char} sharing sweets with friends happily", "{char} and friends eating together",
                   "{char} and friends playing a fun game", "everyone laughing and having fun together",
                   "{char} helping a friend who needs it", "the whole group together in friendship"],
        "camera": ["pan-left", "zoom-in", "pan-right", "zoom-out", "static", "zoom-out"],
    },
]


def fetch_trending_hindi_kids_songs(max_results: int = 10) -> list[dict]:
    if not YOUTUBE_API_KEY:
        return []
    try:
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "key": YOUTUBE_API_KEY, "part": "snippet",
                "q": "hindi kids song cartoon bacchon ka geet",
                "type": "video", "order": "viewCount",
                "relevanceLanguage": "hi", "regionCode": "IN",
                "maxResults": max_results,
            },
            timeout=20,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        return [{"title": it["snippet"]["title"], "channel": it["snippet"]["channelTitle"]} for it in items]
    except Exception:
        return []  # trend fetch is a nice-to-have for tags; never block script generation on it


def build_seo_tags(base_title_english: str, trending: list[dict]) -> list[str]:
    evergreen = ["hindi kids song", "bacchon ke geet", "hindi cartoon", "hindi rhymes",
                 "kids cartoon hindi", "hindi nursery rhymes", "cartoon for kids",
                 "hindi balgeet", "kiddu cartoon", "bachon ka gana", "animated hindi song"]
    tags = [base_title_english.lower()] + evergreen
    seen, out = set(), []
    for t in tags:
        k = t.strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(t.strip())
    return out[:15]


def generate_script(job_id: str = None, n_lines: int = 6) -> dict:
    """Deterministic (seeded by job_id) local script generation -- $0, no Gemini.
    Falls back to a random seed if no job_id given (e.g. ad-hoc/manual runs)."""
    rng = random.Random(job_id) if job_id else random.Random()

    character = rng.choice(CHARACTERS)
    background = rng.choice(BACKGROUNDS)
    theme = rng.choice(THEMES)

    lyric_lines = [line.format(char=character["name"]) for line in theme["lines"]]
    scenes = [
        {"line_index": i, "scene_description": theme["scenes"][i].format(char=character["name"]),
         "camera_move": theme["camera"][i]}
        for i in range(len(theme["scenes"]))
    ]

    trending = fetch_trending_hindi_kids_songs()
    tags = build_seo_tags(character["name"] + " hindi song", trending)

    title = f"{character['name']} की मस्ती भरी कहानी"
    script = {
        "title": title,
        "title_english_transliteration": f"{character['name']} Ki Masti Bhari Kahani",
        "mood": theme["mood"],
        "character": character,
        "background_setting": background,
        "lyrics_lines": lyric_lines,
        "scenes": scenes,
        "youtube_tags": tags,
        "youtube_description": f"{character['name']} ka ek pyara sa gaana bacchon ke liye! "
                                f"An original animated Hindi kids' song, made with love for little ones.",
    }
    return script


if __name__ == "__main__":
    import json
    print(json.dumps(generate_script("test_job"), indent=2, ensure_ascii=False))
