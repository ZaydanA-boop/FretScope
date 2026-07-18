from fretscope import ANALYSIS_SR as SR
from fretscope.tone.features import extract_tone_features
from fretscope.tone.match import compare_tones

from conftest import note_sequence
from test_tone_features import MELODY, drive, reverberate


def _features(y):
    return extract_tone_features(y, SR)


def test_identical_tones_all_close():
    f = _features(note_sequence(MELODY, note_dur=0.5))
    advice = compare_tones(f, f)
    assert advice and all(a.status == "close" for a in advice)


def test_clean_attempt_vs_driven_target_says_add_drive():
    clean = note_sequence(MELODY, note_dur=0.5)
    target = _features(drive(clean, gain=25.0))
    attempt = _features(clean)
    drive_advice = next(a for a in compare_tones(target, attempt)
                        if a.aspect == "drive")
    assert drive_advice.status == "adjust"
    assert drive_advice.delta < 0
    assert "add drive" in drive_advice.text.lower()


def test_dry_attempt_vs_wet_target_says_add_reverb():
    clean = note_sequence(MELODY, note_dur=0.5)
    target = _features(reverberate(clean, t60=2.5))
    attempt = _features(clean)
    rv = next(a for a in compare_tones(target, attempt) if a.aspect == "reverb")
    assert rv.status == "adjust"
    assert "add reverb" in rv.text.lower()


def test_advice_serializes():
    import json
    f = _features(note_sequence(MELODY, note_dur=0.5))
    json.dumps([a.to_dict() for a in compare_tones(f, f)])
