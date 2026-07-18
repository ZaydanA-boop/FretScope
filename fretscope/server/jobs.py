"""Thread-based job runner with on-disk state.

Each job gets a directory under the jobs root:
    jobs/<job_id>/job.json        submitted source, status, stage log
    jobs/<job_id>/report.json     final report (when finished)
    jobs/<job_id>/guitar_stem.wav separated stem (playable from the dashboard)

Analysis is CPU-bound and long (Demucs on CPU takes minutes), so jobs run in a
single worker thread, one at a time, and the dashboard polls job.json state.
"""

from __future__ import annotations

import json
import queue
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..pipeline import analyze


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobManager:
    def __init__(self, root: Path | str = "jobs"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._queue: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()
        self._worker = threading.Thread(target=self._run_loop, daemon=True)
        self._worker.start()
        self._recover_interrupted()

    # ---- public API ---------------------------------------------------------

    def submit(self, source: str, use_separation: bool = True) -> dict:
        job_id = f"{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"
        job_dir = self.root / job_id
        job_dir.mkdir(parents=True)
        state = {
            "id": job_id,
            "source": source,
            "title": self._guess_title(source),
            "use_separation": use_separation,
            "status": "queued",
            "created_at": _now(),
            "stages": [],
        }
        self._write(job_id, state)
        self._queue.put(job_id)
        return state

    def get(self, job_id: str) -> dict | None:
        path = self.root / job_id / "job.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def report(self, job_id: str) -> dict | None:
        path = self.root / job_id / "report.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def stem_path(self, job_id: str) -> Path | None:
        p = self.root / job_id / "guitar_stem.wav"
        return p if p.exists() else None

    def list(self) -> list[dict]:
        jobs = []
        for job_json in sorted(self.root.glob("*/job.json"), reverse=True):
            try:
                jobs.append(json.loads(job_json.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue
        return jobs

    def delete(self, job_id: str) -> bool:
        import shutil
        job_dir = self.root / job_id
        if not (job_dir / "job.json").exists():
            return False
        state = self.get(job_id)
        if state and state["status"] in ("queued", "running"):
            return False  # can't delete active jobs; keep it simple
        shutil.rmtree(job_dir)
        return True

    # ---- internals ----------------------------------------------------------

    def _guess_title(self, source: str) -> str:
        if source.startswith("http"):
            m = re.search(r"[?&]v=([\w-]{6,})", source)
            return f"YouTube {m.group(1)}" if m else "YouTube link"
        return Path(source).stem

    def _write(self, job_id: str, state: dict) -> None:
        with self._lock:
            path = self.root / job_id / "job.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False),
                           encoding="utf-8")
            tmp.replace(path)

    def _recover_interrupted(self) -> None:
        """Jobs left 'running'/'queued' by a previous server process are dead."""
        for state in self.list():
            if state["status"] in ("queued", "running"):
                state["status"] = "failed"
                state["error"] = "interrupted by server restart"
                self._write(state["id"], state)

    def _run_loop(self) -> None:
        while True:
            job_id = self._queue.get()
            state = self.get(job_id)
            if state is None:
                continue
            state["status"] = "running"
            state["started_at"] = _now()
            self._write(job_id, state)

            def progress(stage: str, status: str, detail: str) -> None:
                st = self.get(job_id) or state
                st["stages"] = [s for s in st["stages"] if s["stage"] != stage] + [
                    {"stage": stage, "status": status, "detail": detail,
                     "at": _now()}]
                self._write(job_id, st)

            try:
                report = analyze(state["source"], self.root / job_id,
                                 progress=progress,
                                 use_separation=state.get("use_separation", True))
                (self.root / job_id / "report.json").write_text(
                    json.dumps(report, indent=2, ensure_ascii=False),
                    encoding="utf-8")
                st = self.get(job_id) or state
                st["status"] = "failed" if report.get("error") else "done"
                if report.get("error"):
                    st["error"] = report["error"]
                title = report.get("meta", {}).get("title")
                if title:
                    st["title"] = title
                st["finished_at"] = _now()
                self._write(job_id, st)
            except Exception as e:  # noqa: BLE001 - job must record any failure
                st = self.get(job_id) or state
                st["status"] = "failed"
                st["error"] = str(e)
                st["finished_at"] = _now()
                self._write(job_id, st)
