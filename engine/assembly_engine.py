"""
Assembly Engine — Stage 4.

Combines the silent Ken-Burns video (image_engine) with the final mixed song
(music_engine + vocal_sync_engine) into one professional-looking output, then derives
a vertical Short from it.

Long video: 16:9, full song length, with a simple title card overlay at the start.
Short video: 9:16 crop (center crop + slight zoom), capped at 60s, from the most
visually/energetically interesting slice (currently: first N seconds -- simple and
deterministic; can be swapped for beat-detection later without changing the interface).
"""
import subprocess
from pathlib import Path


def merge_audio_video(video_path: Path, audio_path: Path, out_path: Path):
    """Mux the final song over the silent animated video. -shortest guards against any
    tiny float rounding mismatch between the two independently-built timelines."""
    subprocess.run([
        "ffmpeg", "-y",
        "-i", str(video_path), "-i", str(audio_path),
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(out_path)
    ], check=True, capture_output=True)


def add_title_card(in_path: Path, out_path: Path, title_text: str, duration: float = 2.5):
    """Simple fade-in text title card overlaid on the first `duration` seconds using
    ffmpeg drawtext -- no external title-card asset needed, $0 cost."""
    # escape characters that break ffmpeg drawtext
    safe_text = title_text.replace(":", "\\:").replace("'", "")
    filter_str = (
        f"drawtext=text='{safe_text}':fontcolor=white:fontsize=54:"
        f"x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.4:boxborderw=20:"
        f"enable='lte(t,{duration})':alpha='if(lt(t,0.3),t/0.3,if(gt(t,{duration-0.5}),({duration}-t)/0.5,1))'"
    )
    subprocess.run([
        "ffmpeg", "-y", "-i", str(in_path),
        "-vf", filter_str,
        "-c:a", "copy",
        str(out_path)
    ], check=True, capture_output=True)


def make_short_version(long_video_path: Path, out_path: Path, max_seconds: int = 58):
    """9:16 vertical crop for Shorts: center-crop to a 9:16 window, cap duration, and add
    the #Shorts-friendly aspect ratio ffmpeg expects."""
    subprocess.run([
        "ffmpeg", "-y", "-i", str(long_video_path),
        "-t", str(max_seconds),
        "-vf", "crop=ih*9/16:ih,scale=1080:1920",
        "-c:a", "aac", "-b:a", "192k",
        str(out_path)
    ], check=True, capture_output=True)


def generate_thumbnail(video_path: Path, out_path: Path, timestamp_seconds: float = 1.0):
    subprocess.run([
        "ffmpeg", "-y", "-ss", str(timestamp_seconds), "-i", str(video_path),
        "-frames:v", "1", "-q:v", "2",
        str(out_path)
    ], check=True, capture_output=True)


def assemble_final(job_id: str, silent_video_path: Path, song_path: Path, title: str,
                    video_type: str, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    merged_path = out_dir / f"{job_id}_merged.mp4"
    merge_audio_video(silent_video_path, song_path, merged_path)

    titled_path = out_dir / f"{job_id}_titled.mp4"
    add_title_card(merged_path, titled_path, title)

    result = {"final_video": str(titled_path)}

    if video_type == "short":
        short_path = out_dir / f"{job_id}_short.mp4"
        make_short_version(titled_path, short_path)
        result["final_video"] = str(short_path)

    thumb_path = out_dir / f"{job_id}_thumb.jpg"
    generate_thumbnail(titled_path, thumb_path)
    result["thumbnail"] = str(thumb_path)

    return result
