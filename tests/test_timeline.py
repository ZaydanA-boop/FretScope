import numpy as np

from fretscope import ANALYSIS_SR as SR
from fretscope.tone.timeline import tone_timeline

from conftest import note_sequence
from test_tone_features import MELODY, drive


def two_tone_song():
    """~24 s: clean melody, then the same melody heavily driven."""
    clean = note_sequence(MELODY * 3, note_dur=0.5)
    dirty = drive(note_sequence(MELODY * 3, note_dur=0.5), gain=25.0)
    return np.concatenate([clean, dirty])


def test_timeline_finds_tone_change():
    y = two_tone_song()
    segments = tone_timeline(y, SR)
    assert len(segments) >= 2
    boundary = segments[0].end
    true_change = len(y) / 2 / SR
    assert abs(boundary - true_change) < 5.0, f"boundary {boundary} vs {true_change}"
    assert segments[0].label in ("clean", "edge-of-breakup")
    assert segments[-1].label in ("overdrive", "distortion", "fuzz/high-gain")


def test_single_tone_song_stays_whole():
    y = note_sequence(MELODY * 3, note_dur=0.5)
    segments = tone_timeline(y, SR)
    assert len(segments) == 1
    assert segments[0].start == 0.0


def test_segments_serialize():
    segments = tone_timeline(two_tone_song(), SR)
    import json
    payload = [s.to_dict() for s in segments]
    json.dumps(payload)
    assert all(s["confidence"] == "estimated" for s in payload)
