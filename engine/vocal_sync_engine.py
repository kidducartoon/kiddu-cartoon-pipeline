"""
Vocal Sync Engine — takes the melody line-durations from music_engine.py and the Hindi
lyric lines, generates TTS per line, then time-stretches each line (ffmpeg atempo) so its
spoken duration EXACTLY matches that line's melodic phrase duration. This is what makes
the vocal "ride" the tune instead of just being spoken over it.

Two audio backends:
- edge_tts (real Hindi neural voice) -- requires open internet (works on GitHub Actions,
  NOT in this restricted sandbox).
- stub_tone_backend -- generates a placeholder spoken-cadence tone burst per line, used
  ONLY to prove the timing/stretch pipeline logic works, when edge-tts network is blocked.

Both backends produce a raw per-line WAV; downstream stretch/merge logic is identical,
so swapping backends requires no other code changes.
"""
import asyncio
import subprocess
import json
from pathlib import Path

USE_STUB = False  # GitHub Actions has open network access to speech.platform.bing.com
                 # Flip to False (or delete this override) when running in GitHub Actions.

try:
    import edge_tts
except ImportError:
    edge_tts = None


def line_duration_seconds(n_notes_in_phrase: int, quarter_lengths: list[float], tempo_bpm: int) -> float:
    """Convert a melody phrase's quarter-note lengths + tempo into real seconds."""
    quarter_seconds = 60.0 / tempo_bpm
    return sum(quarter_lengths) * quarter_seconds


async def _edge_tts_line(text: str, out_path: Path, voice: str = "hi-IN-SwaraNeural"):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(out_path))


def _stub_tone_line(text: str, out_path: Path, natural_seconds: float):
    """Placeholder: a soft spoken-cadence tone burst scaled to roughly the line's natural
    speaking length (approx 0.16s/syllable-ish via char count), purely to validate the
    stretch-to-melody pipeline when the real TTS endpoint is unreachable (sandbox only)."""
    approx_len = max(0.6, len(text) * 0.09)
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"sine=frequency=220:duration={approx_len}",
        "-af", "volume=0.3",
        str(out_path)
    ], check=True, capture_output=True)


def generate_tts_line(text: str, out_path: Path, natural_seconds_hint: float = 1.0):
    if USE_STUB or edge_tts is None:
        _stub_tone_line(text, out_path, natural_seconds_hint)
    else:
        asyncio.run(_edge_tts_line(text, out_path))


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
        "stub_mode": USE_STUB
    }, indent=2))
