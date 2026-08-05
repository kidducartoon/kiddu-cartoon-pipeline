"""
Orchestrator — the single entrypoint GitHub Actions / cron-job.org calls.

Usage: python3 orchestrator.py <stage>
  stage in: create_job | script | music | animate | assemble | publish

Each invocation:
  1. Loads state/jobs.json
  2. For 'create_job': makes a new QUEUED job for the given schedule slot
  3. For all other stages: finds every job sitting at the right previous status
     (or FAILED_<this stage>, to retry) and processes each one independently --
     one job's failure never blocks the others (crash-proofing principle).
  4. Commits nothing itself -- the GitHub Actions workflow step commits state/jobs.json
     back to the repo after this script exits, so state is durable across runs.
"""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from state import job_store
from engine import script_engine, music_engine, vocal_sync_engine, image_engine, assembly_engine, publish_engine

WORK_DIR = Path(os.environ.get("PIPELINE_WORK_DIR", "/tmp/kiddu_pipeline"))

# Schedule from the brief: long @ 6/10/14/18 IST, short @ 8/12/16/20 IST
SCHEDULE = {
    "06:00": "long", "08:00": "short", "10:00": "long", "12:00": "short",
    "14:00": "long", "16:00": "short", "18:00": "long", "20:00": "short",
}


def stage_create_job(slot_time_ist: str):
    video_type = SCHEDULE.get(slot_time_ist)
    if not video_type:
        raise ValueError(f"Unknown schedule slot: {slot_time_ist}. Valid: {list(SCHEDULE)}")
    job_id = job_store.create_job(video_type, slot_time_ist)
    print(f"Created job {job_id} ({video_type} @ {slot_time_ist} IST)")


def stage_script():
    jobs = job_store.get_jobs_at_stage("QUEUED") + job_store.get_failed_jobs("script")
    for job in jobs:
        def run(job):
            n_lines = 4 if job["video_type"] == "short" else 8
            script = script_engine.generate_script(n_lines=n_lines)
            return {"script": script}
        job_store.run_stage_safely(job, "script", "SCRIPTED", run)
        print(f"[script] {job['job_id']} -> done")


def stage_music():
    jobs = job_store.get_jobs_at_stage("SCRIPTED") + job_store.get_failed_jobs("music")
    for job in jobs:
        def run(job):
            job_id = job["job_id"]
            script = job["data"]["script"]
            out_dir = WORK_DIR / "music" / job_id
            melody_score, tempo_bpm = music_engine.build_melody(job_id, script["lyrics_lines"], script["mood"])
            midi_path = out_dir / f"{job_id}.mid"
            wav_path = out_dir / f"{job_id}_instrumental.wav"
            out_dir.mkdir(parents=True, exist_ok=True)
            melody_score.write("midi", fp=str(midi_path))
            music_engine.render_to_wav(midi_path, wav_path)

            quarter_seconds = 60.0 / tempo_bpm
            # NOTE: production line-duration extraction should read exact per-line
            # quarterLength sums from build_melody's internal phrase construction;
            # simplified equal-split kept here for the same reason as the validated
            # sandbox prototype -- swap in exact per-line tracking before scaling volume.
            total_notes_quarter = 5 * len(script["lyrics_lines"])  # matches PHRASE_SHAPES avg length
            total_seconds = total_notes_quarter * quarter_seconds * 0.75
            per_line = total_seconds / len(script["lyrics_lines"])
            line_durations = [per_line] * len(script["lyrics_lines"])

            vocal_path = vocal_sync_engine.build_synced_vocal_track(
                job_id, script["lyrics_lines"], line_durations, out_dir
            )
            final_song_path = out_dir / f"{job_id}_final_song.wav"
            vocal_sync_engine.mix_vocals_with_instrumental(vocal_path, wav_path, final_song_path)

            return {"song_path": str(final_song_path), "line_durations": line_durations,
                    "tempo_bpm": tempo_bpm}
        job_store.run_stage_safely(job, "music", "SCORED", run)
        print(f"[music] {job['job_id']} -> done")


def stage_animate():
    jobs = job_store.get_jobs_at_stage("SCORED") + job_store.get_failed_jobs("animate")
    for job in jobs:
        def run(job):
            job_id = job["job_id"]
            script = job["data"]["script"]
            line_durations = job["data"]["line_durations"]
            out_dir = WORK_DIR / "video" / job_id
            seed = music_engine.seed_from_job_id(job_id)
            silent_video = image_engine.build_animated_video(job_id, script, line_durations, out_dir, seed)
            return {"silent_video_path": str(silent_video)}
        job_store.run_stage_safely(job, "animate", "ANIMATED", run)
        print(f"[animate] {job['job_id']} -> done")


def stage_assemble():
    jobs = job_store.get_jobs_at_stage("ANIMATED") + job_store.get_failed_jobs("assemble")
    for job in jobs:
        def run(job):
            job_id = job["job_id"]
            script = job["data"]["script"]
            out_dir = WORK_DIR / "final" / job_id
            result = assembly_engine.assemble_final(
                job_id,
                Path(job["data"]["silent_video_path"]),
                Path(job["data"]["song_path"]),
                script["title"],
                job["video_type"],
                out_dir,
            )
            return result
        job_store.run_stage_safely(job, "assemble", "RENDERED", run)
        print(f"[assemble] {job['job_id']} -> done")


def stage_publish():
    jobs = job_store.get_jobs_at_stage("RENDERED") + job_store.get_failed_jobs("publish")
    for job in jobs:
        def run(job):
            script = job["data"]["script"]
            result = publish_engine.publish_job(
                job["job_id"],
                Path(job["data"]["final_video"]),
                Path(job["data"]["thumbnail"]),
                script,
                drive_file_id=job["data"].get("drive_file_id"),
            )
            return result
        job_store.run_stage_safely(job, "publish", "PUBLISHED", run)
        print(f"[publish] {job['job_id']} -> done")


STAGES = {
    "create_job": stage_create_job,
    "script": stage_script,
    "music": stage_music,
    "animate": stage_animate,
    "assemble": stage_assemble,
    "publish": stage_publish,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in STAGES:
        print(f"Usage: python3 orchestrator.py <{'|'.join(STAGES)}> [args]")
        sys.exit(1)
    stage = sys.argv[1]
    if stage == "create_job":
        if len(sys.argv) < 3:
            print("Usage: python3 orchestrator.py create_job <HH:MM>")
            sys.exit(1)
        stage_create_job(sys.argv[2])
    else:
        STAGES[stage]()
