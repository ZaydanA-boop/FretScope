from pathlib import Path

import numpy as np

import fretscope.separation as separation
from fretscope.audio_io import save_wav
from fretscope.separation import FALLBACK_NOTE, separate_guitar


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
