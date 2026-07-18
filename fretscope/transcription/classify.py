"""Decide whether a guitar part is a lead line or a chordal rhythm part.

Plain English: a lead line is one note at a time; a rhythm part is several notes
ringing together. We estimate "how many pitches sound at once" from the chroma
(energy per pitch class per moment). If most moments have one dominant pitch class,
it's a lead; if energy is spread across three or more, it's chords.

This is a heuristic (label: heuristic). Known failure modes: heavy distortion adds
harmonics that look like extra pitches; delay/reverb smears notes into each other;
double-tracked leads look chordal.
"""

from __future__ import annotations

from dataclasses import dataclass

import librosa
import numpy as np


@dataclass
class PartClassification:
    kind: str                 # "lead" | "rhythm"
    mean_active_pitches: float
    confidence: float         # 0..1, distance from the decision boundary
    rationale: str


# Chroma bins count as "active" above this fraction of the frame's peak bin.
ACTIVE_REL_THRESHOLD = 0.6
# Mean simultaneous active pitch classes at/above this ⇒ chordal. Calibrated on
# synthesized fixtures: monophonic lines measure ~1.1, strummed triads ~1.9-2.0
# (decaying chord tails collapse toward their strongest note, so triads measure
# below 3). A distorted lead whose 3rd harmonic (root+fifth) is strong could
# cross this boundary — documented failure mode.
CHORDAL_BOUNDARY = 1.6


def classify_part(y: np.ndarray, sr: int) -> PartClassification:
    if len(y) < sr // 4 or float(np.max(np.abs(y))) < 1e-4:
        return PartClassification("lead", 0.0, 0.0, "audio too short/quiet to classify")

    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    frame_rms = librosa.feature.rms(y=y)[0]
    # Only judge frames that actually contain signal
    loud = frame_rms[: chroma.shape[1]] > (np.max(frame_rms) * 0.1)
    if loud.sum() < 4:
        loud = np.ones(chroma.shape[1], dtype=bool)
    chroma = chroma[:, loud[: chroma.shape[1]]]

    peak = np.max(chroma, axis=0, keepdims=True) + 1e-9
    active = (chroma / peak) >= ACTIVE_REL_THRESHOLD
    mean_active = float(np.mean(active.sum(axis=0)))

    kind = "rhythm" if mean_active >= CHORDAL_BOUNDARY else "lead"
    confidence = float(min(1.0, abs(mean_active - CHORDAL_BOUNDARY) / 0.5))
    rationale = (
        f"on average {mean_active:.1f} pitch classes sound at once "
        f"(boundary {CHORDAL_BOUNDARY}: fewer = lead, more = chords)"
    )
    return PartClassification(kind, mean_active, confidence, rationale)
