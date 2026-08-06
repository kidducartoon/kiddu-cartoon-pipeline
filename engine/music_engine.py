"""
Music Engine — generates a UNIQUE instrumental track per video, $0 cost, no external
music APIs. Uses music21 to procedurally compose melody+chords from the song's lyric
structure (line count, syllable rhythm, mood), renders MIDI -> WAV via fluidsynth.

Design goals:
- Deterministic given a random seed (so a failed job can be safely re-run / resumed
  without producing a different song than a partially-completed prior attempt).
- Unique per video (seed derived from video's unique job ID).
- Mood-aware: picks scale/tempo/instrument based on a simple "mood" tag from the script
  (happy, calm, playful, lullaby) so 8 songs/day don't all sound identical.
"""
import random
import hashlib
import subprocess
import json
import sys
from pathlib import Path

from music21 import stream, note, chord, meter, tempo, instrument, key as m21key

SOUNDFONT = "/usr/share/sounds/sf2/FluidR3_GM.sf2"

MOODS = {
    "happy":   {"scale": "major", "tempo": (120, 140), "instrument": instrument.Xylophone()},
    "playful": {"scale": "major", "tempo": (110, 130), "instrument": instrument.Marimba()},
    "calm":    {"scale": "major", "tempo": (80, 95),   "instrument": instrument.Flute()},
    "lullaby": {"scale": "major", "tempo": (60, 75),   "instrument": instrument.Celesta()},
}

# Simple diatonic scale degrees biased toward pleasant, singable, stepwise motion
# (kids' songs rarely leap far) — encoded as scale-degree sequences per phrase shape.
PHRASE_SHAPES = [
    [1, 2, 3, 2, 1],
    [1, 3, 5, 3, 1],
    [5, 4, 3, 2, 1],
    [1, 2, 3, 5, 3],
    [3, 3, 2, 2, 1],
    [1, 1, 5, 5, 6, 6, 5],  # twinkle-twinkle-ish shape, good for kids' songs
]


def seed_from_job_id(job_id: str) -> int:
    """Deterministic seed so re-running the same job_id (crash-recovery) regenerates
    the identical song rather than a different one."""
    return int(hashlib.sha256(job_id.encode()).hexdigest(), 16) % (2**31)


def build_melody(job_id: str, lyric_lines: list[str], mood: str = "happy",
                  key_tonic: str = "C") -> stream.Score:
    if mood not in MOODS:
        mood = "happy"
    cfg = MOODS[mood]

    rng = random.Random(seed_from_job_id(job_id))
    tempo_bpm = rng.randint(*cfg["tempo"])

    sc = stream.Score()
    melody_part = stream.Part()
    melody_part.insert(0, cfg["instrument"])
    melody_part.insert(0, tempo.MetronomeMark(number=tempo_bpm))
    melody_part.insert(0, meter.TimeSignature("4/4"))
    melody_part.insert(0, m21key.Key(key_tonic))

    chord_part = stream.Part()
    chord_part.insert(0, instrument.AcousticGuitar())
    chord_part.insert(0, meter.TimeSignature("4/4"))

    k = m21key.Key(key_tonic)
    scale_pitches = k.getScale("major").getPitches(f"{key_tonic}4", f"{key_tonic}5")

    # simple I-IV-V-I / I-V-vi-IV style progressions, picked per song (unique per job)
    progressions = [
        [1, 4, 5, 1], [1, 5, 6, 4], [1, 6, 4, 5], [1, 4, 1, 5],
    ]
    progression = rng.choice(progressions)

    n_lines = max(1, len(lyric_lines))
    line_quarter_lengths = []  # exact per-line duration in quarter-notes, in order
    for i in range(n_lines):
        shape = rng.choice(PHRASE_SHAPES)
        degree_root = progression[i % len(progression)]
        line_total = 0.0
        for deg in shape:
            idx = (degree_root - 1 + deg - 1) % len(scale_pitches)
            p = scale_pitches[idx]
            dur = rng.choice([0.5, 0.5, 1.0])  # mostly eighths/quarters -> singable
            n = note.Note(p)
            n.quarterLength = dur
            melody_part.append(n)
            line_total += dur
        line_quarter_lengths.append(line_total)

        # one sustained chord per line, matching the melody's harmonic root
        root_idx = (progression[i % len(progression)] - 1) % len(scale_pitches)
        c = chord.Chord([scale_pitches[root_idx], scale_pitches[(root_idx + 2) % len(scale_pitches)],
                          scale_pitches[(root_idx + 4) % len(scale_pitches)]])
        c.quarterLength = line_total  # bugfix: was independently re-randomized before,
                                       # causing chords to drift out of sync with the
                                       # melody after a few lines. Now guaranteed to match.
        chord_part.append(c)

    sc.insert(0, melody_part)
    sc.insert(0, chord_part)
    return sc, tempo_bpm, line_quarter_lengths


def render_to_wav(midi_path: Path, wav_path: Path):
    """MIDI -> WAV using fluidsynth + free GM soundfont. $0, fully offline, no API."""
    subprocess.run(
        ["fluidsynth", "-ni", SOUNDFONT, str(midi_path),
         "-F", str(wav_path), "-r", "44100"],
        check=True, capture_output=True, text=True
    )


def line_durations_seconds(line_quarter_lengths: list[float], tempo_bpm: int) -> list[float]:
    """Exact per-line duration in real seconds, derived from the melody's own quarter-note
    lengths -- no approximation. This is what vocal_sync_engine should use to time each
    TTS line, so vocals lock to the melody exactly rather than an equal-split guess."""
    quarter_seconds = 60.0 / tempo_bpm
    return [q * quarter_seconds for q in line_quarter_lengths]


def generate_song_instrumental(job_id: str, lyric_lines: list[str], mood: str,
                                out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    midi_path = out_dir / f"{job_id}.mid"
    wav_path = out_dir / f"{job_id}_instrumental.wav"

    score, tempo_bpm, line_quarter_lengths = build_melody(job_id, lyric_lines, mood)
    score.write("midi", fp=str(midi_path))
    render_to_wav(midi_path, wav_path)

    return {
        "job_id": job_id,
        "mood": mood,
        "tempo_bpm": tempo_bpm,
        "midi_path": str(midi_path),
        "wav_path": str(wav_path),
        "seed": seed_from_job_id(job_id),
        "line_durations_sec": line_durations_seconds(line_quarter_lengths, tempo_bpm),
    }


if __name__ == "__main__":
    # Self-test: generate 2 different jobs to prove uniqueness + determinism
    lines_a = ["Chalo dosto chalo", "Hum karte hain masti", "Gaate hain ye geet", "Milkar sabhi saathi"]
    result_a = generate_song_instrumental("test_job_001", lines_a, "happy", Path("/home/claude/music_out"))
    result_b = generate_song_instrumental("test_job_002", lines_a, "lullaby", Path("/home/claude/music_out"))
    # re-run job_001 to prove determinism (crash-recovery safe)
    result_a2 = generate_song_instrumental("test_job_001", lines_a, "happy", Path("/home/claude/music_out"))

    print(json.dumps({"job_001": result_a, "job_002": result_b,
                       "job_001_rerun_matches_seed": result_a["seed"] == result_a2["seed"],
                       "job_001_rerun_matches_durations":
                           result_a["line_durations_sec"] == result_a2["line_durations_sec"]}, indent=2))
