from pathlib import Path

import numpy as np

import fretscope.separation as separation
from fretscope.audio_io import save_wav
from fretscope.separation import (BLEND_NOTE, FALLBACK_NOTE, OTHER_ONLY_NOTE,
                                  _pick_guitar_stem, separate_guitar)


def test_fallback_without_demucs(tmp_path: Path, lead_line, monkeypatch):
    """Core requirement: pipeline must work (flagged) when torch/demucs are absent."""
    monkeypatch.setattr(separation, "separation_available", lambda: False)
    src = save_wav(tmp_path / "mix.wav", lead_line)
    res = separate_guitar(src, tmp_path / "work")
    assert res.separated is False
    assert res.stem_name == "full_mix"
    assert res.method == "none"
    assert FALLBACK_NOTE in res.notes
    assert isinstance(res.audio, np.ndarray) and len(res.audio) > 0


def test_pick_guitar_stem_prefers_dedicated_stem():
    loud = np.ones(1000, dtype=np.float32) * 0.5
    quiet = np.ones(1000, dtype=np.float32) * 0.01
    stem, name, _ = _pick_guitar_stem({"guitar": loud, "other": quiet})
    assert name == "guitar"
    assert np.array_equal(stem, loud)


def test_pick_guitar_stem_blends_when_guitar_nearly_empty():
    loud = np.ones(1000, dtype=np.float32) * 0.5
    quiet = np.ones(1000, dtype=np.float32) * 0.01
    stem, name, notes = _pick_guitar_stem({"guitar": quiet, "other": loud})
    assert name == "guitar+other"
    assert BLEND_NOTE in notes
    assert np.allclose(stem, quiet + loud)


def test_pick_guitar_stem_four_stem_model():
    other = np.ones(1000, dtype=np.float32) * 0.3
    stem, name, notes = _pick_guitar_stem({"other": other})
    assert name == "other"
    assert OTHER_ONLY_NOTE in notes
