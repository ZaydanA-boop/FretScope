import importlib
import time

import pytest
from fastapi.testclient import TestClient

from fretscope.audio_io import save_wav


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FRETSCOPE_JOBS_DIR", str(tmp_path / "jobs"))
    import fretscope.server.app as app_module
    importlib.reload(app_module)  # rebind JobManager to the temp jobs dir
    with TestClient(app_module.app) as c:
        yield c


def test_health(client):
    h = client.get("/api/health").json()
    assert h["ok"] is True and h["ffmpeg"] is True


def test_dashboard_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "FretScope" in res.text


def test_job_lifecycle(client, tmp_path, lead_line):
    src = save_wav(tmp_path / "song.wav", lead_line)

    bad = client.post("/api/jobs", json={"source": "not-a-real-thing"})
    assert bad.status_code == 422

    job = client.post("/api/jobs", json={"source": str(src),
                                         "use_separation": False}).json()
    assert job["status"] == "queued"

    deadline = time.time() + 120
    while time.time() < deadline:
        state = client.get(f"/api/jobs/{job['id']}").json()
        if state["status"] in ("done", "failed"):
            break
        time.sleep(0.5)
    assert state["status"] == "done", state.get("error")
    assert any(s["stage"] == "transcribe" for s in state["stages"])

    report = client.get(f"/api/jobs/{job['id']}/report").json()
    assert report["transcription"]["kind"] == "lead"

    stem = client.get(f"/api/jobs/{job['id']}/stem")
    assert stem.status_code == 200
    assert stem.headers["content-type"].startswith("audio/")

    assert client.delete(f"/api/jobs/{job['id']}").json()["deleted"] == job["id"]
    assert client.get(f"/api/jobs/{job['id']}").status_code == 404
