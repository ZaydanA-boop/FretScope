import numpy as np

from fretscope import ANALYSIS_SR as SR
from fretscope.transcription.chords import recognize_chords
from fretscope.transcription.musicfacts import analyze_facts

from conftest import chord, note_sequence


def test_key_detection_a_minor():
    """A natural-minor scale walk should read as A minor (or its relative C major)."""
    a_minor_scale = [220.0, 246.94, 261.63, 293.66, 329.63, 349.23, 392.0, 440.0]
    y = note_sequence(a_minor_scale * 2, note_dur=0.4)
    facts = analyze_facts(y, SR)
    assert facts.key in ("A minor", "C major"), facts.key
    assert facts.to_dict()["confidence"] == "heuristic"


def test_tempo_reasonable():
    y = note_sequence([220.0, 261.63, 329.63, 392.0] * 4, note_dur=0.5)
    facts = analyze_facts(y, SR)
    # notes at 0.5 s = 120 bpm; accept the half/double octave errors typical
    # of tempo estimation
    assert 55 <= facts.tempo_bpm <= 250


def test_tuning_near_standard():
    y = note_sequence([220.0, 261.63, 329.63, 440.0], note_dur=0.5)
    facts = analyze_facts(y, SR)
    assert abs(facts.tuning_cents) < 25


def test_dominant_seventh_recognized():
    # A7: A C# E G
    y = chord([110.0, 138.59, 164.81, 196.0, 220.0, 277.18], dur=2.0)
    labels = [s.label for s in recognize_chords(y, SR) if s.label != "N"]
    assert labels, "no chords found"
    top = max(set(labels), key=labels.count)
    assert top in ("A7", "A"), top  # 7th preferred, plain triad acceptable


def test_triads_still_win_on_plain_triads(a_minor_chord, c_major_chord):
    am = [s.label for s in recognize_chords(a_minor_chord, SR) if s.label != "N"]
    c = [s.label for s in recognize_chords(c_major_chord, SR) if s.label != "N"]
    assert max(set(am), key=am.count) == "Am"
    assert max(set(c), key=c.count) == "C"
