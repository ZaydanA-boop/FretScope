"""Learned tone parameter model: features → concrete effect settings.

Plain English: instead of hand-written rules ("crest below X probably means
overdrive"), we *generate* thousands of guitar clips with known effect settings
(a drive pedal at 17 dB, a reverb at 40% wet...), measure the same features we
measure on real songs, and train a model to run that mapping in reverse.

Honesty box, read before trusting numbers:
- The training guitars are synthesized plucked strings, and the effects are one
  software chain (pedalboard's Distortion/Reverb/Delay). A real amp's clipping
  and a real spring reverb behave differently. The predictions transfer roughly,
  not exactly — which is why they ship with the model's own test error attached
  and stay labeled `estimated`.
- If the committed model file is missing, everything degrades to the heuristic
  rules in mapping.py; nothing depends on the model existing.

Training lives in train.py; this module only loads and applies the result.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from .features import BANDS, ToneFeatures

MODEL_DIR = Path(__file__).resolve().parent / "models"
MODEL_PATH = MODEL_DIR / "tone_model.joblib"
METRICS_PATH = MODEL_DIR / "tone_model_metrics.json"

# Input vector layout — training and inference must agree exactly.
FEATURE_ORDER = [
    "rms_db", "crest_db", "flat_top_ratio", "harmonic_distortion",
    "spectral_centroid_hz", "tilt_db_per_octave", "decay_t60_s",
    "dynamic_range_db", "modulation_hz", "modulation_depth",
    "echo_delay_s", "echo_strength", "subband_mod_hz", "subband_mod_depth",
]
# Model outputs, in order. Chorus is model-only: no hand-written rule detects it
# reliably (validated against synthetic chorus), but the forest reads it out of
# the joint feature set — see the experiment note in CLAUDE.md.
TARGETS = ["drive_db", "reverb_wet", "reverb_room", "delay_seconds", "delay_mix",
           "chorus_rate_hz", "chorus_mix"]


def features_to_vector(f: ToneFeatures) -> np.ndarray:
    d = f.to_dict()
    scalars = [float(d[name]) for name in FEATURE_ORDER]
    bands = [float(d["band_energy"][b]) for b in BANDS]
    return np.array(scalars + bands, dtype=np.float64)


@lru_cache(maxsize=1)
def _load():
    if not MODEL_PATH.exists():
        return None
    import joblib
    model = joblib.load(MODEL_PATH)
    metrics = {}
    if METRICS_PATH.exists():
        metrics = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    return model, metrics


def model_available() -> bool:
    return _load() is not None


def predict_params(f: ToneFeatures) -> dict | None:
    """Predict effect settings for one feature set, with the model's test MAE.

    Returns e.g. {"drive_db": {"value": 17.2, "mae": 3.1}, ...} or None when no
    model is installed.
    """
    loaded = _load()
    if loaded is None:
        return None
    model, metrics = loaded
    x = features_to_vector(f).reshape(1, -1)
    y = model.predict(x)[0]
    mae = metrics.get("test_mae", {})
    out = {}
    for name, value in zip(TARGETS, y):
        out[name] = {
            "value": round(float(max(value, 0.0)), 3),
            "mae": round(float(mae.get(name, 0.0)), 3) if mae else None,
        }
    out["note"] = (
        "Predicted by a model trained on synthesized effect chains, not real "
        "amps — treat as a starting point with roughly the stated error."
    )
    return out
