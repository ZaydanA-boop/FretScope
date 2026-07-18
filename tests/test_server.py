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
    assert "model_available" in h and "separation_available" in h


def test_upload_job(client, tmp_path, lead_line):
    import io
    import time
    src = save_wav(tmp_path / "riff take 3.wav", lead_line)
    res = client.post("/api/jobs/upload",
                      files={"audio": ("riff take 3.wav",
                                       io.BytesIO(src.read_bytes()), "audio/wav")},
                      data={"use_separation": "false"})
    assert res.status_code == 200, res.text
    job = res.json()
    assert job["title"] == "riff take 3"
    deadline = time.time() + 120
    while time.time() < deadline:
        state = client.get(f"/api/jobs/{job['id']}").json()
        if state["status"] in ("done", "failed"):
            break
        time.sleep(0.5)
    assert state["status"] == "done", state.get("error")


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

    # closed-loop tone matching: upload an "attempt" against the finished job
    import io
    wav_bytes = (tmp_path / "song.wav").read_bytes()
    match = client.post(f"/api/jobs/{job['id']}/match",
                        files={"audio": ("attempt.wav", io.BytesIO(wav_bytes),
                                         "audio/wav")},
                        data={"segment": -1})
    assert match.status_code == 200, match.text
    payload = match.json()
    assert payload["confidence"] == "estimated"
    aspects = {a["aspect"] for a in payload["advice"]}
    assert {"drive", "brightness", "reverb"} <= aspects

    assert client.delete(f"/api/jobs/{job['id']}").json()["deleted"] == job["id"]
    assert client.get(f"/api/jobs/{job['id']}").status_code == 404
