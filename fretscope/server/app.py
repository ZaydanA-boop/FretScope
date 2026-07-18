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

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..audio_io import find_ffmpeg, is_youtube_url
from ..separation import separation_available
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


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> dict:
    if not manager.delete(job_id):
        raise HTTPException(409, "job not found or still active")
    return {"deleted": job_id}


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="dashboard")
