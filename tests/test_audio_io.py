from pathlib import Path

import numpy as np

from fretscope import ANALYSIS_SR
from fretscope.audio_io import (find_ffmpeg, is_youtube_url, load_audio, save_wav,
                                to_wav, trim_wav, wav_duration)


def test_save_and_load_roundtrip(tmp_path: Path, sine_a4):
    p = save_wav(tmp_path / "a4.wav", sine_a4)
    y, sr = load_audio(p)
    assert sr == ANALYSIS_SR
    assert y.dtype == np.float32
    assert abs(len(y) - len(sine_a4)) < 4
    assert np.max(np.abs(y - sine_a4)) < 1e-3


def test_trim_and_duration(tmp_path: Path, sine_a4):
    import numpy as np
    long = np.tile(sine_a4, 5)  # 5 s
    src = save_wav(tmp_path / "long.wav", long)
    assert abs(wav_duration(src) - 5.0) < 0.05
    out = trim_wav(src, tmp_path / "short.wav", 2.0)
    assert abs(wav_duration(out) - 2.0) < 0.1


def test_is_youtube_url():
    assert is_youtube_url("https://www.youtube.com/watch?v=abc123")
    assert is_youtube_url("https://youtu.be/abc123")
    assert not is_youtube_url("song.mp3")
    assert not is_youtube_url("https://example.com/watch?v=abc")


def test_ffmpeg_available_and_transcodes(tmp_path: Path, sine_a4):
    # ffmpeg is a hard project requirement; fail loudly if discovery breaks.
    assert find_ffmpeg() is not None
    src = save_wav(tmp_path / "in.wav", sine_a4, sr=44100)
    out = to_wav(src, tmp_path / "out.wav", sr=ANALYSIS_SR)
    y, sr = load_audio(out)
    assert sr == ANALYSIS_SR
    # 1 s of 44.1k audio resampled to 22.05k should still be ~1 s
    assert abs(len(y) / sr - len(sine_a4) / 44100) < 0.05
