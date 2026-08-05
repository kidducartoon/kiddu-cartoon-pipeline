"""
Image + Animation Engine — Stage 3.

Image generation: uses Pollinations.ai's free, keyless image API (https://image.pollinations.ai)
-- genuinely $0, no signup, no API key, generous for automation use. Not as good as paid
Stable Diffusion/Midjourney, but meets the "$0 cost" constraint.

Character consistency: every scene's prompt is built from the SAME character description
string (from the script's `character.appearance` field) plus a fixed style suffix, so the
mascot looks the same across all scenes/videos rather than drifting.

Animation: ffmpeg Ken Burns (slow pan/zoom) per scene image -> per-scene video clip, timed
to match that scene's line_duration from the music engine, then concatenated.
"""
import os
import subprocess
import urllib.parse
import requests
from pathlib import Path

STYLE_SUFFIX = (
    "pixar disney style 3d render, soft lighting, vibrant colors, rounded friendly shapes, "
    "children's cartoon illustration, high quality, detailed, wholesome, no text, no watermark"
)

CAMERA_MOVES = {
    # ffmpeg zoompan expressions: (zoom expr, x expr, y expr)
    "static":    dict(z="1.0", x="0", y="0"),
    "zoom-in":   dict(z="'min(zoom+0.0015,1.15)'", x="'iw/2-(iw/zoom/2)'", y="'ih/2-(ih/zoom/2)'"),
    "zoom-out":  dict(z="'if(eq(on,1),1.15,max(zoom-0.0015,1.0))'", x="'iw/2-(iw/zoom/2)'", y="'ih/2-(ih/zoom/2)'"),
    "pan-left":  dict(z="1.1", x="'max(0,(iw-iw/zoom)*(1-on/duration_frames))'", y="'ih/2-(ih/zoom/2)'"),
    "pan-right": dict(z="1.1", x="'max(0,(iw-iw/zoom)*(on/duration_frames))'", y="'ih/2-(ih/zoom/2)'"),
}


def build_scene_prompt(character_appearance: str, background_setting: str, scene_description: str) -> str:
    return f"{character_appearance}, {scene_description}, background: {background_setting}, {STYLE_SUFFIX}"


def generate_scene_image(prompt: str, out_path: Path, seed: int, width=1280, height=720):
    """Pollinations.ai keyless image API. `seed` makes character/style reproducible across
    a job's re-runs (crash-recovery safe) while still being unique per video (seed derived
    from job_id upstream)."""
    encoded = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded}?width={width}&height={height}&seed={seed}&nologo=true"
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(resp.content)


def render_ken_burns_clip(image_path: Path, out_path: Path, duration_seconds: float,
                           camera_move: str = "static", fps: int = 30, width=1280, height=720):
    move = CAMERA_MOVES.get(camera_move, CAMERA_MOVES["static"])
    n_frames = max(1, int(duration_seconds * fps))
    zoompan = (
        f"zoompan=z={move['z']}:x={move['x']}:y={move['y']}:d={n_frames}:s={width}x{height}:fps={fps}"
    )
    subprocess.run([
        "ffmpeg", "-y", "-loop", "1", "-i", str(image_path),
        "-vf", zoompan, "-t", f"{duration_seconds:.3f}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(out_path)
    ], check=True, capture_output=True)


def concat_clips(clip_paths: list[Path], out_path: Path):
    concat_list = out_path.parent / "concat_video_list.txt"
    with open(concat_list, "w") as f:
        for p in clip_paths:
            f.write(f"file '{p.resolve()}'\n")
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_list), "-c", "copy", str(out_path)
    ], check=True, capture_output=True)


def build_animated_video(job_id: str, script: dict, line_durations: list[float],
                          out_dir: Path, seed: int) -> Path:
    """Generate one image + Ken Burns clip per scene, matching each scene's music-derived
    duration exactly, then concat into the silent video track (audio is merged later in
    the assembly stage)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    character = script["character"]["appearance"]
    background = script["background_setting"]

    clip_paths = []
    for i, scene in enumerate(script["scenes"]):
        prompt = build_scene_prompt(character, background, scene["scene_description"])
        img_path = out_dir / f"{job_id}_scene{i:02d}.jpg"
        generate_scene_image(prompt, img_path, seed=seed + i)

        dur = line_durations[i] if i < len(line_durations) else line_durations[-1]
        clip_path = out_dir / f"{job_id}_scene{i:02d}.mp4"
        render_ken_burns_clip(img_path, clip_path, dur, scene.get("camera_move", "static"))
        clip_paths.append(clip_path)

    silent_video_path = out_dir / f"{job_id}_silent_video.mp4"
    concat_clips(clip_paths, silent_video_path)
    return silent_video_path


if __name__ == "__main__":
    # Self-test with a tiny 2-scene mock script (real network call to Pollinations)
    mock_script = {
        "character": {"appearance": "a cheerful round little elephant named Chintu, big ears, blue skin, red bow tie"},
        "background_setting": "a sunny green meadow with flowers and a rainbow",
        "scenes": [
            {"scene_description": "Chintu the elephant waving happily", "camera_move": "zoom-in"},
            {"scene_description": "Chintu dancing with butterflies around him", "camera_move": "pan-right"},
        ],
    }
    out = build_animated_video("selftest_job", mock_script, [3.0, 3.0], Path("/home/claude/image_out"), seed=42)
    print("Built:", out)
