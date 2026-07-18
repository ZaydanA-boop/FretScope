import json
from pathlib import Path

from fretscope.audio_io import save_wav
from fretscope.pipeline import analyze
from fretscope.report import render_markdown


def test_pipeline_lead_end_to_end(tmp_path: Path, lead_line):
    src = save_wav(tmp_path / "song.wav", lead_line)
    report = analyze(str(src), tmp_path / "work", use_separation=False)

    assert "error" not in report
    assert report["separation"]["separated"] is False
    assert report["transcription"]["kind"] == "lead"
    assert report["transcription"]["confidence"] == "heuristic"
    assert len(report["transcription"]["notes"]) >= 4
    assert report["tone"]["confidence"] == "estimated"
    assert report["limitations"]
    # report must be JSON-serializable as-is
    json.dumps(report)

    md = report["markdown"]
    assert "## Tab" in md and "## Tone breakdown" in md and "Limitations" in md
    assert "confidence: heuristic" in md and "confidence: estimated" in md


def test_pipeline_rhythm_end_to_end(tmp_path: Path, a_minor_chord):
    import numpy as np
    strums = np.concatenate([a_minor_chord] * 3)
    src = save_wav(tmp_path / "chords.wav", strums)
    report = analyze(str(src), tmp_path / "work", use_separation=False)
    assert report["transcription"]["kind"] == "rhythm"
    labels = [c["chord"] for c in report["transcription"]["chords"] if c["chord"] != "N"]
    assert "Am" in labels
    assert "## Chord chart" in report["markdown"]


def test_pipeline_survives_bad_input(tmp_path: Path):
    report = analyze(str(tmp_path / "nope.mp3"), tmp_path / "work")
    assert report.get("error")
    assert "Analysis failed" in render_markdown(report)
