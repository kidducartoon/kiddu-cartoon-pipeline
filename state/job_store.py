"""
Job State Machine — the backbone of crash-proofing.

Every video is a "job" with a unique ID and a status. This file (state/jobs.json) is
committed back to the repo by every GitHub Actions run, so state survives across runs,
across days, and across crashes. No job is ever silently lost or double-processed:

STAGES (in order):
  QUEUED        -> job created (topic/slot picked), nothing generated yet
  SCRIPTED      -> Gemini script + lyrics + scene list generated
  SCORED        -> instrumental + vocal + mixed song generated
  ANIMATED      -> per-scene images + Ken Burns clips generated
  RENDERED      -> final video (long + short) assembled
  PUBLISHED     -> uploaded to YouTube, Drive temp files deleted
  FAILED_<stage> -> an error occurred; job stays here with error info for retry

RESUME LOGIC: each pipeline stage script only picks up jobs whose status equals the
PREVIOUS stage's completion status (or a FAILED_<its own stage>, to retry). It never
touches jobs already past its stage. This makes every stage idempotent and safe to
re-run after a crash, a GitHub Actions timeout, or a cron double-fire.
"""
import json
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone

JOBS_FILE = Path(__file__).parent / "jobs.json"

STAGE_ORDER = ["QUEUED", "SCRIPTED", "SCORED", "ANIMATED", "RENDERED", "PUBLISHED"]


def _now():
    return datetime.now(timezone.utc).isoformat()


def load_jobs() -> dict:
    if not JOBS_FILE.exists():
        return {}
    with open(JOBS_FILE) as f:
        return json.load(f)


def save_jobs(jobs: dict):
    JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(JOBS_FILE, "w") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)


def create_job(video_type: str, slot_time_ist: str, mood: str = "happy") -> str:
    """video_type: 'long' or 'short'. slot_time_ist: e.g. '06:00' matching the schedule."""
    jobs = load_jobs()
    job_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d')}_{slot_time_ist.replace(':','')}_{video_type}_{uuid.uuid4().hex[:6]}"
    jobs[job_id] = {
        "job_id": job_id,
        "video_type": video_type,
        "slot_time_ist": slot_time_ist,
        "mood": mood,
        "status": "QUEUED",
        "created_at": _now(),
        "updated_at": _now(),
        "history": [{"status": "QUEUED", "at": _now()}],
        "error": None,
        "data": {},  # each stage stashes its output paths/metadata here
    }
    save_jobs(jobs)
    return job_id


def get_jobs_at_stage(status: str) -> list[dict]:
    """Jobs sitting at exactly this status -- i.e. ready for the NEXT stage to pick up."""
    jobs = load_jobs()
    return [j for j in jobs.values() if j["status"] == status]


def get_failed_jobs(stage: str) -> list[dict]:
    jobs = load_jobs()
    return [j for j in jobs.values() if j["status"] == f"FAILED_{stage}"]


def advance_job(job_id: str, new_status: str, data_update: dict = None):
    jobs = load_jobs()
    if job_id not in jobs:
        raise ValueError(f"Unknown job_id: {job_id}")
    jobs[job_id]["status"] = new_status
    jobs[job_id]["updated_at"] = _now()
    jobs[job_id]["history"].append({"status": new_status, "at": _now()})
    if data_update:
        jobs[job_id]["data"].update(data_update)
    if not new_status.startswith("FAILED_"):
        jobs[job_id]["error"] = None
    save_jobs(jobs)


def fail_job(job_id: str, stage: str, error_message: str):
    jobs = load_jobs()
    if job_id not in jobs:
        raise ValueError(f"Unknown job_id: {job_id}")
    jobs[job_id]["status"] = f"FAILED_{stage}"
    jobs[job_id]["updated_at"] = _now()
    jobs[job_id]["error"] = error_message
    jobs[job_id]["history"].append({"status": f"FAILED_{stage}", "at": _now(), "error": error_message})
    save_jobs(jobs)


def run_stage_safely(job: dict, stage_name: str, next_status: str, fn):
    """Wrap a stage's processing function with crash-proof error handling.
    fn(job) should return a dict of data to merge into job['data'], or raise on failure.
    On any exception: job is marked FAILED_<stage_name> with the error, and the pipeline
    moves on to the next job rather than halting -- one bad job never blocks the channel."""
    job_id = job["job_id"]
    try:
        result_data = fn(job) or {}
        advance_job(job_id, next_status, result_data)
        return True
    except Exception as e:
        fail_job(job_id, stage_name, f"{type(e).__name__}: {e}")
        return False


if __name__ == "__main__":
    # self-test
    jid = create_job("long", "06:00", "happy")
    print("created:", jid)
    advance_job(jid, "SCRIPTED", {"title": "test song"})
    print(load_jobs()[jid])
