import numpy as np
import scipy.signal

from fretscope import ANALYSIS_SR as SR
from fretscope.tone.features import extract_tone_features
from fretscope.tone.mapping import estimate_tone

from conftest import note_sequence
from test_tone_features import MELODY, drive, reverberate


def _estimate(y):
    return estimate_tone(extract_tone_features(y, SR))


def test_clean_maps_clean():
    est = _estimate(note_sequence(MELODY, note_dur=0.5))
    assert est.chain[0].effect in ("clean", "edge-of-breakup")
    assert est.confidence == "estimated"


def test_distorted_maps_dirty():
    est = _estimate(drive(note_sequence(MELODY, note_dur=0.5), gain=25.0))
    assert est.chain[0].effect in ("distortion", "fuzz/high-gain", "overdrive")
    assert est.chain[0].strength > 0.3


def test_reverb_appears_in_chain():
    est = _estimate(reverberate(note_sequence(MELODY, note_dur=0.5), t60=2.5))
    assert any(e.effect == "reverb" for e in est.chain)


def test_tremolo_appears_in_chain():
    y = note_sequence(MELODY, note_dur=0.5)
    t = np.arange(len(y)) / SR
    trem = (y * (0.55 + 0.45 * np.sin(2 * np.pi * 5.0 * t))).astype(np.float32)
    est = _estimate(trem)
    mods = [e for e in est.chain if e.effect == "modulation"]
    assert mods and "5" in mods[0].settings["rate"]


def test_every_estimate_labeled_estimated():
    est = _estimate(drive(reverberate(note_sequence(MELODY, note_dur=0.5))))
    assert est.confidence == "estimated"
    assert all(e.confidence == "estimated" for e in est.chain)
    d = est.to_dict()
    assert d["confidence"] == "estimated"
    # never phrased as identification
    text = (d["summary"] + " ".join(e["verdict"] for e in d["chain"])).lower()
    assert "identified" not in text and "detected pedal" not in text


def test_amp_eq_present():
    est = _estimate(note_sequence(MELODY, note_dur=0.5))
    assert {"bass", "mids", "treble"} <= set(est.amp_eq)
