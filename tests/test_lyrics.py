"""Lyrics are optional at every level; these tests cover the glue, not whisper."""

from fretscope.lyrics import attach_chords, lyrics_available


def test_attach_chords_by_midpoint():
    lines = [{"start": 0.0, "end": 2.0, "text": "hello darkness"},
             {"start": 2.0, "end": 4.0, "text": "my old friend"},
             {"start": 10.0, "end": 12.0, "text": "outside any chord"}]
    chords = [{"chord": "Am", "start": 0.0, "end": 2.5},
              {"chord": "N", "start": 2.5, "end": 2.8},
              {"chord": "F", "start": 2.8, "end": 5.0}]
    out = attach_chords(lines, chords)
    assert out[0]["chord"] == "Am"
    assert out[1]["chord"] == "F"
    assert out[2]["chord"] is None


def test_attach_chords_handles_empty():
    assert attach_chords([], []) == []
    lines = [{"start": 0, "end": 1, "text": "la"}]
    assert attach_chords(lines, [])[0]["chord"] is None


def test_lyrics_available_is_bool():
    assert isinstance(lyrics_available(), bool)
