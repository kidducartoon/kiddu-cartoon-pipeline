# Kiddu Cartoon Pipeline

Fully automated Hindi kids' musical cartoon video pipeline: script (Gemini) -> music
(procedural, $0) -> vocals (edge-tts, synced to melody) -> animation (stylized 2.5D,
Pollinations.ai) -> assembly (ffmpeg) -> YouTube publish, orchestrated by cron-job.org
hitting GitHub Actions, with crash-proof resumable state.

## How it works

Every video is a "job" tracked in `state/jobs.json`, moving through stages:
`QUEUED -> SCRIPTED -> SCORED -> ANIMATED -> RENDERED -> PUBLISHED`. Each stage is its own
GitHub Actions run, picks up every job sitting at the right previous stage, and commits
the updated state back to the repo. If a stage fails for one job, that job is marked
`FAILED_<stage>` with the error and retried automatically on the next run -- nothing else
is blocked, and nothing is lost.

## Required GitHub secrets (Settings -> Secrets and variables -> Actions)

| Secret | Where to get it |
|---|---|
| `YOUTUBE_API_KEY` | Google Cloud Console -> enable "YouTube Data API v3" -> Credentials -> API key |
| `GEMINI_API_KEY` | Google AI Studio (aistudio.google.com) -> Get API key (free tier) |
| `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET` | Google Cloud Console -> OAuth client (Desktop app type) for the channel's own Google account |
| `YOUTUBE_REFRESH_TOKEN` | Generated once via OAuth consent flow with scope `https://www.googleapis.com/auth/youtube.upload` (run locally once; see below) |
| `GDRIVE_SERVICE_ACCOUNT_JSON` | Google Cloud Console -> Service Account -> JSON key -> base64-encode it (`base64 -w0 key.json`) |
| `GDRIVE_BUFFER_FOLDER_ID` | The Drive folder ID used as short-term video storage before publish (share it with the service account's email) |

**Getting a YouTube refresh token (one-time, manual, cannot be automated for security
reasons -- Google requires a human consent click):**
```
pip install google-auth-oauthlib
python3 -c "
from google_auth_oauthlib.flow import InstalledAppFlow
flow = InstalledAppFlow.from_client_secrets_file('client_secret.json',
    scopes=['https://www.googleapis.com/auth/youtube.upload'])
creds = flow.run_local_server(port=0)
print('REFRESH TOKEN:', creds.refresh_token)
"
```

## Scheduling via cron-job.org

Create 8 daily job-creation crons + 5 pipeline-stage crons hitting the GitHub Actions
`repository_dispatch` API (needs a GitHub token with `actions:write` as a Bearer header
in cron-job.org's custom headers):

**Job-creation crons** (IST times from the brief), each POSTs:
```
URL: https://api.github.com/repos/kidducartoon/kiddu-cartoon-pipeline/dispatches
Method: POST
Headers:
  Authorization: Bearer <YOUR_GITHUB_TOKEN>
  Accept: application/vnd.github+json
Body: {"event_type": "run_stage", "client_payload": {"stage": "create_job_0600"}}
```
Repeat for `create_job_0800`, `create_job_1000`, `create_job_1200`, `create_job_1400`,
`create_job_1600`, `create_job_1800`, `create_job_2000` at their matching IST times.

**Pipeline-stage crons** (run frequently, e.g. every 15-30 min, so jobs flow through
promptly after creation): `script`, `music`, `animate`, `assemble`, `publish` -- same
URL/headers, body `{"event_type": "run_stage", "client_payload": {"stage": "script"}}`
(swap the stage name per cron job).

This decouples "when a video is scheduled to go live" from "how long each stage takes",
which is what makes the pipeline resumable and crash-proof: a slow or failed stage just
means that job sits a bit longer at its current status until the next cron tick retries it.

## Known limitations (see project chat for full discussion)

- Music is procedurally generated MIDI-quality (fluidsynth + GM soundfont) -- genuinely
  $0 and unique per video, but not studio-produced quality.
- Vocals are edge-tts speech time-stretched to match the melody's rhythm -- a rhythmic
  chant, not true singing.
- Visuals are 2.5D (AI still images + Ken Burns pan/zoom), not true 3D rendering.
- Image generation uses Pollinations.ai's free keyless API -- quality/consistency is
  best-effort at this price point; consider a paid image API if quality is insufficient.
- `edge-tts` and `image.pollinations.ai` are unreachable from a restricted dev sandbox;
  both were validated for logic/timing only there and need real validation on the first
  live GitHub Actions run (see project chat).
