import numpy as np

from fretscope import ANALYSIS_SR as SR
from fretscope.transcription.chords import recognize_chords, render_chart
from fretscope.transcription.classify import classify_part
from fretscope.transcription.fretting import (STANDARD_TUNING, assign_frets,
                                              candidate_positions)
from fretscope.transcription.pitch import Note, extract_notes
from fretscope.transcription.tab import render_tab


def test_classify_lead_vs_rhythm(lead_line, a_minor_chord):
    assert classify_part(lead_line, SR).kind == "lead"
    assert classify_part(a_minor_chord, SR).kind == "rhythm"


def test_extract_notes_recovers_melody(lead_line):
    notes = extract_notes(lead_line, SR)
    got = [n.midi for n in notes]
    # A3 C4 D4 E4 G4 A4
    expected = [57, 60, 62, 64, 67, 69]
    # pitch tracking may split/miss an edge note; require the melody as a subsequence
    it = iter(got)
    assert all(any(m == e for m in it) for e in expected), f"melody {expected} not in {got}"
    assert all(n.confidence > 0.3 for n in notes)


def test_candidate_positions_share_pitch():
    for midi in (40, 52, 64, 76):
        cands = candidate_positions(midi)
        assert cands, f"no positions for midi {midi}"
        for s, f in cands:
            assert STANDARD_TUNING[s] + f == midi


def test_assign_frets_playable_and_correct():
    melody = [Note(m, i * 0.4, 0.35, 0.9) for i, m in enumerate([57, 60, 62, 64, 67, 69])]
    fretted = assign_frets(melody)
    assert len(fretted) == len(melody)
    for fn in fretted:
        assert STANDARD_TUNING[fn.string] + fn.fret == fn.note.midi
        assert 0 <= fn.fret <= 19
    # playability: consecutive fretted notes shouldn't leap more than 7 frets
    frets = [fn.fret for fn in fretted if fn.fret > 0]
    assert all(abs(a - b) <= 7 for a, b in zip(frets, frets[1:]))


def test_render_tab_shape():
    melody = [Note(m, i * 0.4, 0.35, 0.9) for i, m in enumerate([57, 60, 62])]
    tab = render_tab(assign_frets(melody))
    lines = tab.splitlines()
    assert len(lines) == 6
    assert lines[0].startswith("e|") and lines[5].startswith("E|")
    assert all(len(l) == len(lines[0]) for l in lines)


def test_recognize_chords(a_minor_chord, c_major_chord):
    am = [s.label for s in recognize_chords(a_minor_chord, SR) if s.label != "N"]
    c = [s.label for s in recognize_chords(c_major_chord, SR) if s.label != "N"]
    assert am and max(set(am), key=am.count) == "Am"
    assert c and max(set(c), key=c.count) == "C"


def test_render_chart_readable(a_minor_chord):
    chart = render_chart(recognize_chords(a_minor_chord, SR))
    assert "Am" in chart and "s" in chart
