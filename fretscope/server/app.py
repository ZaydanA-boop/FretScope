"""FastAPI app: JSON API + static dashboard.

Endpoints:
    POST   /api/jobs            {"source": "<youtube url or path>", "use_separation": bool}
    GET    /api/jobs            all jobs, newest first
    GET    /api/jobs/{id}       one job's state (stage log for progress UI)
    GET    /api/jobs/{id}/report
    GET    /api/jobs/{id}/stem  separated guitar stem as WAV
    DELETE /api/jobs/{id}
    GET    /api/health          separation availability etc.
    GET    /                    dashboard
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..audio_io import find_ffmpeg, is_youtube_url
from ..separation import separation_available
from ..tone.learned import model_available
from .jobs import JobManager

app = FastAPI(title="FretScope", docs_url="/api/docs")

JOBS_ROOT = Path(os.environ.get("FRETSCOPE_JOBS_DIR", "jobs"))
manager = JobManager(JOBS_ROOT)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class JobRequest(BaseModel):
    source: str
    use_separation: bool = True


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "ffmpeg": find_ffmpeg() is not None,
        "separation_available": separation_available(),
        "model_available": model_available(),
    }


@app.post("/api/jobs")
def create_job(req: JobRequest) -> dict:
    source = req.source.strip()
    if not source:
        raise HTTPException(422, "source is empty")
    if not is_youtube_url(source) and not Path(source).exists():
        raise HTTPException(422, "source must be a YouTube URL or an existing "
                                 "audio file path on this machine")
    return manager.submit(source, use_separation=req.use_separation)


@app.post("/api/jobs/upload")
async def create_job_from_upload(audio: UploadFile = File(...),
                                 use_separation: bool = Form(True)) -> dict:
    """Drag-and-drop / file-picker path: store the file, then queue it."""
    import uuid

    name = Path(audio.filename or "upload.bin")
    uploads = JOBS_ROOT / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    dest = uploads / f"{uuid.uuid4().hex[:10]}{name.suffix or '.bin'}"
    dest.write_bytes(await audio.read())
    return manager.submit(str(dest), use_separation=use_separation,
                          title=name.stem)


@app.get("/api/jobs")
def list_jobs() -> list[dict]:
    return manager.list()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    state = manager.get(job_id)
    if state is None:
        raise HTTPException(404, "no such job")
    return state


@app.get("/api/jobs/{job_id}/report")
def get_report(job_id: str) -> dict:
    report = manager.report(job_id)
    if report is None:
        raise HTTPException(404, "report not ready")
    return report


@app.get("/api/jobs/{job_id}/stem")
def get_stem(job_id: str) -> FileResponse:
    path = manager.stem_path(job_id)
    if path is None:
        raise HTTPException(404, "stem not available")
    return FileResponse(path, media_type="audio/wav", filename="guitar_stem.wav")


@app.post("/api/jobs/{job_id}/match")
async def match_tone(job_id: str, audio: UploadFile = File(...),
                     segment: int = Form(-1)) -> dict:
    """Compare an uploaded/recorded attempt against the song's target tone.

    `segment` picks a tone-timeline section (-1 = whole song).
    """
    report = manager.report(job_id)
    if report is None:
        raise HTTPException(404, "report not ready")
    tone = report.get("tone", {})
    timeline = tone.get("timeline", [])
    if 0 <= segment < len(timeline):
        target_dict = timeline[segment]["features"]
        target_name = f"section {segment + 1}"
    elif tone.get("features"):
        target_dict = tone["features"]
        target_name = "whole song"
    else:
        raise HTTPException(409, "this job has no tone analysis to match against")

    from ..audio_io import load_audio
    from ..tone.features import extract_tone_features, features_from_dict
    from ..tone.learned import predict_params
    from ..tone.match import CAVEAT, compare_tones

    job_dir = manager.root / job_id
    suffix = Path(audio.filename or "attempt.webm").suffix or ".webm"
    attempt_path = job_dir / f"attempt{suffix}"
    attempt_path.write_bytes(await audio.read())
    try:
        y, sr = load_audio(attempt_path)  # ffmpeg decodes webm/ogg/wav alike
        attempt = extract_tone_features(y, sr)
    except Exception as e:
        raise HTTPException(422, f"could not analyze the recording: {e}") from e

    target = features_from_dict(target_dict)
    advice = compare_tones(target, attempt,
                           target_params=predict_params(target),
                           attempt_params=predict_params(attempt))
    return {
        "target": target_name,
        "advice": [a.to_dict() for a in advice],
        "caveat": CAVEAT,
        "confidence": "estimated",
        "attempt_features": attempt.to_dict(),
    }


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> dict:
    if not manager.delete(job_id):
        raise HTTPException(409, "job not found or still active")
    return {"deleted": job_id}


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="dashboard")
