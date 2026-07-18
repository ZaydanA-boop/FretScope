"""The learned model is optional by design: everything must work without it,
and when it exists its predictions must be shaped and labeled correctly."""

from fretscope import ANALYSIS_SR as SR
from fretscope.tone.features import extract_tone_features
from fretscope.tone.learned import (TARGETS, features_to_vector, model_available,
                                    predict_params)

from conftest import note_sequence
from test_tone_features import MELODY, drive


def test_feature_vector_shape():
    f = extract_tone_features(note_sequence(MELODY, note_dur=0.5), SR)
    v = features_to_vector(f)
    assert v.shape == (16,)


def test_predict_params_optional():
    f = extract_tone_features(note_sequence(MELODY, note_dur=0.5), SR)
    params = predict_params(f)
    if not model_available():
        assert params is None
        return
    assert set(TARGETS) <= set(params)
    for t in TARGETS:
        assert params[t]["value"] >= 0.0
    assert "synthesized" in params["note"]


def test_model_says_more_drive_for_driven_audio():
    if not model_available():
        return  # model not trained on this machine; optional path covered above
    clean = note_sequence(MELODY, note_dur=0.5)
    f_clean = extract_tone_features(clean, SR)
    f_dirty = extract_tone_features(drive(clean, gain=25.0), SR)
    p_clean = predict_params(f_clean)["drive_db"]["value"]
    p_dirty = predict_params(f_dirty)["drive_db"]["value"]
    assert p_dirty > p_clean + 3.0
