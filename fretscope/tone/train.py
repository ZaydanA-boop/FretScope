"""Generate a labeled tone dataset and train the parameter model.

Run from the repo root (takes ~10-20 minutes, CPU):

    .venv\\Scripts\\python.exe -m fretscope.tone.train

What it does, in plain English: build a few hundred short synthetic guitar
clips, run each through a random effect chain whose settings we therefore KNOW
(drive dB, reverb wet/room, delay time/mix), measure our standard tone features
on the processed audio, and fit a random forest that maps features back to the
settings. The train/test split MAE per parameter is saved next to the model and
shipped to the UI as the model's honesty label.

Design choices:
- Clips are Karplus-Strong plucks (riffs and strums) — no copyrighted audio,
  and the same synthesis the test suite uses. The domain gap to real guitar is
  real and documented in learned.py.
- Zero-inflated targets: when an effect is off, its parameters are 0. The model
  learns "no reverb" as wet≈0 rather than via a separate classifier.
"""

from __future__ import annotations

import json

import numpy as np

from .. import ANALYSIS_SR as SR
from .features import extract_tone_features
from .learned import FEATURE_ORDER, MODEL_DIR, MODEL_PATH, METRICS_PATH, TARGETS, \
    features_to_vector

N_SAMPLES = 700
CLIP_SECONDS = 3.0

# Pentatonic-ish pitch pool across the guitar's range (Hz)
PITCH_POOL = [82.41, 98.0, 110.0, 130.81, 146.83, 164.81, 196.0, 220.0,
              246.94, 293.66, 329.63, 392.0, 440.0, 523.25]


def _pluck(freq: float, dur: float, rng: np.random.Generator) -> np.ndarray:
    n = int(SR * dur)
    period = max(2, int(round(SR / freq)))
    buf = rng.uniform(-1, 1, period)
    out = np.empty(n)
    for i in range(n):
        out[i] = buf[i % period]
        buf[i % period] = 0.996 * 0.5 * (buf[i % period] + buf[(i + 1) % period])
    return out / (np.max(np.abs(out)) + 1e-9)


def _base_clip(rng: np.random.Generator) -> np.ndarray:
    """A short riff (70%) or strummed chord pattern (30%)."""
    if rng.random() < 0.7:
        note_dur = rng.uniform(0.25, 0.6)
        n_notes = max(3, int(CLIP_SECONDS / note_dur))
        freqs = rng.choice(PITCH_POOL, size=n_notes)
        y = np.concatenate([_pluck(f, note_dur, rng) for f in freqs])
    else:
        root = float(rng.choice(PITCH_POOL[:8]))
        ratios = [1.0, 1.25, 1.5] if rng.random() < 0.5 else [1.0, 1.189, 1.5]
        strum_dur = rng.uniform(0.8, 1.5)
        n_strums = max(2, int(CLIP_SECONDS / strum_dur))
        strums = []
        for _ in range(n_strums):
            voices = [_pluck(root * r * o, strum_dur, rng)
                      for r in ratios for o in (1, 2)]
            strums.append(np.sum(voices, axis=0))
        y = np.concatenate(strums)
    y = y[: int(CLIP_SECONDS * SR)]
    return (y / (np.max(np.abs(y)) + 1e-9)).astype(np.float32)


def _random_chain(rng: np.random.Generator):
    """Random effect chain + the ground-truth parameter vector."""
    from pedalboard import Chorus, Delay, Distortion, Pedalboard, Reverb

    params = dict.fromkeys(TARGETS, 0.0)
    fx = []
    if rng.random() < 0.7:
        params["drive_db"] = float(rng.uniform(2.0, 35.0))
        fx.append(Distortion(drive_db=params["drive_db"]))
    if rng.random() < 0.4:
        params["chorus_rate_hz"] = float(rng.uniform(0.5, 3.0))
        params["chorus_mix"] = float(rng.uniform(0.25, 0.6))
        fx.append(Chorus(rate_hz=params["chorus_rate_hz"],
                         depth=float(rng.uniform(0.3, 0.8)),
                         centre_delay_ms=float(rng.uniform(5.0, 10.0)),
                         mix=params["chorus_mix"]))
    if rng.random() < 0.4:
        params["delay_seconds"] = float(rng.uniform(0.12, 0.7))
        params["delay_mix"] = float(rng.uniform(0.1, 0.45))
        fx.append(Delay(delay_seconds=params["delay_seconds"],
                        feedback=float(rng.uniform(0.1, 0.5)),
                        mix=params["delay_mix"]))
    if rng.random() < 0.6:
        params["reverb_room"] = float(rng.uniform(0.1, 0.95))
        params["reverb_wet"] = float(rng.uniform(0.05, 0.5))
        fx.append(Reverb(room_size=params["reverb_room"],
                         wet_level=params["reverb_wet"], dry_level=0.8))
    return Pedalboard(fx), params


def build_dataset(n: int = N_SAMPLES, seed: int = 42):
    rng = np.random.default_rng(seed)
    X, Y = [], []
    for i in range(n):
        clip = _base_clip(rng)
        board, params = _random_chain(rng)
        processed = board(clip, SR) if len(board) else clip
        processed = np.asarray(processed, dtype=np.float32).flatten()
        peak = float(np.max(np.abs(processed)) + 1e-9)
        processed = processed / peak
        try:
            f = extract_tone_features(processed, SR)
        except ValueError:
            continue
        X.append(features_to_vector(f))
        Y.append([params[t] for t in TARGETS])
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{n} clips rendered + measured", flush=True)
    return np.array(X), np.array(Y)


def train(seed: int = 42) -> dict:
    import joblib
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.metrics import mean_absolute_error
    from sklearn.model_selection import train_test_split

    print("Building dataset (synthesized clips through known effect chains)...")
    X, Y = build_dataset(seed=seed)
    print(f"Dataset: {X.shape[0]} samples, {X.shape[1]} features")

    X_tr, X_te, Y_tr, Y_te = train_test_split(X, Y, test_size=0.2,
                                              random_state=seed)
    model = RandomForestRegressor(n_estimators=120, max_depth=14,
                                  random_state=seed, n_jobs=-1)
    model.fit(X_tr, Y_tr)

    pred = model.predict(X_te)
    mae = {t: float(mean_absolute_error(Y_te[:, i], pred[:, i]))
           for i, t in enumerate(TARGETS)}
    print("Held-out MAE per parameter:")
    for t, v in mae.items():
        print(f"  {t:14s} {v:.3f}")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH, compress=3)
    metrics = {
        "n_samples": int(X.shape[0]),
        "n_features": int(X.shape[1]),
        "feature_order": FEATURE_ORDER + [f"band:{b}" for b in
                                          ["low", "mid", "presence", "treble"]],
        "targets": TARGETS,
        "test_mae": mae,
        "training_domain": "synthesized Karplus-Strong guitar through pedalboard "
                           "Distortion/Delay/Reverb — NOT real amps; see learned.py",
    }
    METRICS_PATH.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"Saved {MODEL_PATH.name} "
          f"({MODEL_PATH.stat().st_size / 1e6:.1f} MB) and metrics.")
    return metrics


if __name__ == "__main__":
    train()
