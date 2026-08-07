"""
Vocal Sync Engine — times Hindi lines to match each melody phrase's duration exactly,
then generates the actual vocal audio and mixes it with the instrumental.

TTS backend: Piper (https://github.com/rhasspy/piper), MIT licensed, runs fully OFFLINE
with real neural voice models (no network call at synthesis time). Switched from edge-tts
after confirming edge-tts's reverse-engineered Microsoft protocol is currently blocked in
production (real error seen on a live GitHub Actions run: "WSServerHandshakeError: 403"
connecting to speech.platform.bing.com) -- an unofficial API Microsoft can and does break
at any time. Piper has no such risk since it never talks to a remote service at all.

The Hindi voice model (hi_IN-pratham-medium, ONNX + config) is downloaded once by the
GitHub Actions workflow (see .github/workflows/pipeline.yml) into PIPER_MODEL_DIR, cached
between runs so it isn't re-downloaded every 15 minutes.
"""
import os
import subprocess
from pathlib import Path

PIPER_MODEL_DIR = Path(os.environ.get("PIPER_MODEL_DIR", "/home/runner/piper_voices"))
PIPER_MODEL_NAME = "hi_IN-pratham-medium"


def line_duration_seconds(n_notes_in_phrase: int, quarter_lengths: list[float], tempo_bpm: int) -> float:
    """Convert a melody phrase's quarter-note lengths + tempo into real seconds."""
    quarter_seconds = 60.0 / tempo_bpm
    return sum(quarter_lengths) * quarter_seconds


def _piper_tts_line(text: str, out_path: Path):
    """Synthesize one line of Hindi text to a WAV file using the local, offline Piper
    model. Piper reads input text from stdin and writes a WAV file to -f."""
    model_path = PIPER_MODEL_DIR / f"{PIPER_MODEL_NAME}.onnx"
    config_path = PIPER_MODEL_DIR / f"{PIPER_MODEL_NAME}.onnx.json"
    subprocess.run(
        ["piper", "-m", str(model_path), "-c", str(config_path), "-f", str(out_path)],
        input=text.encode("utf-8"),
        check=True, capture_output=True,
    )


def generate_tts_line(text: str, out_path: Path, natural_seconds_hint: float = 1.0):
    _piper_tts_line(text, out_path)


def stretch_to_duration(in_path: Path, out_path: Path, target_seconds: float):
    """Time-stretch (not pitch-shift) audio to exactly target_seconds using ffmpeg atempo.
    atempo only supports 0.5-2.0 per filter instance, so chain filters for extreme ratios."""
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(in_path)],
        capture_output=True, text=True, check=True
    )
    current = float(probe.stdout.strip())
    if current <= 0:
        current = 0.1
    ratio = current / target_seconds  # >1 means audio is longer than target -> speed up

    # Chain atempo filters to cover ratios outside [0.5, 2.0]
    filters = []
    remaining = ratio
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.4f}")
    filter_str = ",".join(filters)

    subprocess.run([
        "ffmpeg", "-y", "-i", str(in_path),
        "-filter:a", filter_str,
        "-t", f"{target_seconds:.4f}",
        str(out_path)
    ], check=True, capture_output=True)


def build_synced_vocal_track(job_id: str, lyric_lines: list[str], line_durations: list[float],
                              out_dir: Path) -> Path:
    """Generate + stretch every lyric line to match its melody phrase, then concat into
    one continuous vocal track whose total length == sum(line_durations), i.e. exactly
    matches the instrumental's timeline so the two can be mixed with zero drift."""
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = out_dir / f"{job_id}_raw_lines"
    raw_dir.mkdir(exist_ok=True)

    stretched_paths = []
    for i, (line, dur) in enumerate(zip(lyric_lines, line_durations)):
        raw_path = raw_dir / f"line_{i:02d}.mp3"
        generate_tts_line(line, raw_path, natural_seconds_hint=dur)

        stretched_path = raw_dir / f"line_{i:02d}_stretched.wav"
        stretch_to_duration(raw_path, stretched_path, dur)
        stretched_paths.append(stretched_path)

    # concat all stretched lines into one continuous vocal track
    concat_list = raw_dir / "concat_list.txt"
    with open(concat_list, "w") as f:
        for p in stretched_paths:
            f.write(f"file '{p.resolve()}'\n")

    vocal_out = out_dir / f"{job_id}_vocals.wav"
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_list), "-c", "copy", str(vocal_out)
    ], check=True, capture_output=True)

    return vocal_out


def mix_vocals_with_instrumental(vocal_path: Path, instrumental_path: Path, out_path: Path):
    """Mix synced vocals over instrumental. Vocal track duration should already match
    the instrumental's timeline exactly (both derived from the same line_durations)."""
    subprocess.run([
        "ffmpeg", "-y",
        "-i", str(instrumental_path), "-i", str(vocal_path),
        "-filter_complex",
        "[0:a]volume=0.55[inst];[1:a]volume=1.0[voc];[inst][voc]amix=inputs=2:duration=longest:dropout_transition=2[out]",
        "-map", "[out]", str(out_path)
    ], check=True, capture_output=True)


if __name__ == "__main__":
    # Reuse the exact same job as before to prove vocal timeline == instrumental timeline
    import sys
    sys.path.insert(0, "/home/claude")
    from music_engine import build_melody, line_durations_seconds, render_to_wav, seed_from_job_id

    job_id = "test_job_001"
    lyric_lines = ["Chalo dosto chalo", "Hum karte hain masti", "Gaate hain ye geet", "Milkar sabhi saathi"]

    # exact per-line durations straight from the melody builder -- no approximation
    # (this used to re-derive an equal-split estimate here; build_melody now returns
    # the real per-line quarterLength sums directly, so use those instead)
    score, tempo_bpm, line_quarter_lengths = build_melody(job_id, lyric_lines, "happy")
    line_durations = line_durations_seconds(line_quarter_lengths, tempo_bpm)

    out_dir = Path("/home/claude/music_out")
    vocal_path = build_synced_vocal_track(job_id, lyric_lines, line_durations, out_dir)

    instrumental_path = out_dir / f"{job_id}_instrumental.wav"
    final_mixed = out_dir / f"{job_id}_final_mixed.wav"
    mix_vocals_with_instrumental(vocal_path, instrumental_path, final_mixed)

    print(json.dumps({
        "vocal_track": str(vocal_path),
        "final_mixed": str(final_mixed),
        "line_durations_sec": line_durations,
        "total_seconds": sum(line_durations),
        "backend": "piper"
    }, indent=2))
