"""Tone features are validated *relatively*: apply a known effect to a clean signal
and check the relevant metric moves the right way. That's the honest claim the
module makes — direction, not absolute accuracy."""

import numpy as np
import pytest
import scipy.signal

from fretscope import ANALYSIS_SR as SR
from fretscope.tone.features import extract_tone_features

from conftest import note_sequence

MELODY = [220.0, 261.63, 293.66, 329.63, 392.0, 440.0, 392.0, 329.63]


@pytest.fixture(scope="module")
def clean():
    return note_sequence(MELODY, note_dur=0.5)


def drive(y, gain=12.0):
    """Hard-ish clipping distortion."""
    out = np.tanh(gain * y)
    return (out / np.max(np.abs(out))).astype(np.float32)


def reverberate(y, t60=2.0, sr=SR):
    """Convolve with an exponentially decaying noise impulse response."""
    rng = np.random.default_rng(3)
    n = int(sr * t60)
    ir = rng.standard_normal(n) * np.exp(-6.9 * np.arange(n) / n)  # −60 dB at t60
    ir[0] = 1.0
    wet = scipy.signal.fftconvolve(y, ir * 0.35)[: len(y) + n]
    return (wet / np.max(np.abs(wet))).astype(np.float32)


def test_distortion_raises_distortion_metrics(clean):
    f_clean = extract_tone_features(clean, SR)
    f_dirty = extract_tone_features(drive(clean), SR)
    # Plucked strings are already harmonic-rich, so the ratio moves, not explodes:
    # direction + a real margin is the honest assertion.
    assert f_dirty.harmonic_distortion > f_clean.harmonic_distortion + 0.2
    assert f_dirty.flat_top_ratio > f_clean.flat_top_ratio + 0.05
    assert f_dirty.crest_db < f_clean.crest_db - 3.0


def test_clean_riff_not_mistaken_for_tremolo_or_echo(clean):
    """Rhythmic playing pulses the envelope at the note rate; the detectors must
    not report that as tremolo or delay."""
    f = extract_tone_features(clean, SR)
    assert f.modulation_depth == 0.0 or not (1.5 < f.modulation_hz < 2.5)
    assert f.echo_strength == 0.0 or not (0.42 < f.echo_delay_s < 0.58)


def test_reverb_lengthens_decay(clean):
    f_clean = extract_tone_features(clean, SR)
    f_wet = extract_tone_features(reverberate(clean), SR)
    assert f_wet.decay_t60_s > f_clean.decay_t60_s + 0.3


def test_compression_shrinks_dynamics(clean):
    comp = np.tanh(3.0 * clean)
    comp = (comp / np.max(np.abs(comp))).astype(np.float32)
    f_clean = extract_tone_features(clean, SR)
    f_comp = extract_tone_features(comp, SR)
    assert f_comp.crest_db < f_clean.crest_db
    assert f_comp.dynamic_range_db <= f_clean.dynamic_range_db + 1.0


def test_tremolo_detected(clean):
    t = np.arange(len(clean)) / SR
    rate = 5.0
    trem = (clean * (0.55 + 0.45 * np.sin(2 * np.pi * rate * t))).astype(np.float32)
    f = extract_tone_features(trem, SR)
    assert f.modulation_hz == pytest.approx(rate, abs=0.6)
    assert f.modulation_depth > 0.05


def test_eq_tilt_direction(clean):
    sos_lp = scipy.signal.butter(4, 800, "lowpass", fs=SR, output="sos")
    sos_hp = scipy.signal.butter(4, 2000, "highpass", fs=SR, output="sos")
    dark = scipy.signal.sosfilt(sos_lp, clean).astype(np.float32)
    bright = scipy.signal.sosfilt(sos_hp, clean).astype(np.float32)
    f_dark = extract_tone_features(dark, SR)
    f_bright = extract_tone_features(bright, SR)
    assert f_dark.tilt_db_per_octave < f_bright.tilt_db_per_octave
    assert f_dark.spectral_centroid_hz < f_bright.spectral_centroid_hz


def test_band_energy_sane(clean):
    f = extract_tone_features(clean, SR)
    assert 0.5 < sum(f.band_energy.values()) <= 1.01
    assert f.to_dict()["rms_db"] == f.rms_db
