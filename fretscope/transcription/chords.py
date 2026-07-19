"""Chord recognition: chordal audio → a timed chord chart.

Plain English: we measure how much energy each of the 12 pitch classes (C, C#, D, …)
has over time, then ask which chord's notes best explain that energy — like matching
a fingerprint against a card file of 24 chords (12 major + 12 minor triads).

Deliberately simple and explainable (label: heuristic). Not covered yet: 7ths,
suspensions, inversions, slash chords, key detection. A dominant 7th will usually
come back as its plain major triad.
"""

from __future__ import annotations

from dataclasses import dataclass

import librosa
import numpy as np

PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Frame decisions are taken every SEGMENT seconds, then identical neighbours merge.
SEGMENT = 0.25
MIN_SIMILARITY = 0.6      # below this cosine similarity ⇒ "N" (no confident chord)
SILENCE_RMS_REL = 0.08    # frames quieter than 8% of peak RMS ⇒ silence
# Hysteresis: keep the current chord unless a challenger beats it by this margin.
# Rationale: as a chord decays, weaker chord tones fade first and the tail becomes
# ambiguous (an Am tail with the C gone matches "A" as well as "Am"); without
# stickiness every decay produces a phantom chord change.
SWITCH_MARGIN = 0.05


@dataclass
class ChordSpan:
    label: str        # e.g. "Am", "C", or "N" for no-chord
    start: float
    end: float
    similarity: float  # mean template similarity over the span (0..1)


# Triads plus the three everyday 7th flavors. 7th templates are down-weighted
# so a plain triad wins unless the 7th is clearly in the audio: string harmonics
# alone deposit energy on 7th degrees (the third's own 3rd harmonic IS the
# major 7th), so an even fight would relabel most triads as 7th chords.
_QUALITIES = (
    ("", (0, 4, 7), 1.0),
    ("m", (0, 3, 7), 1.0),
    ("7", (0, 4, 7, 10), 0.94),
    ("maj7", (0, 4, 7, 11), 0.94),
    ("m7", (0, 3, 7, 10), 0.94),
)


def _templates() -> tuple[list[str], np.ndarray]:
    labels, rows = [], []
    for root in range(12):
        for quality, intervals, weight in _QUALITIES:
            v = np.zeros(12)
            v[[(root + i) % 12 for i in intervals]] = 1.0
            labels.append(PITCH_CLASSES[root] + quality)
            rows.append(weight * v / np.linalg.norm(v))
    return labels, np.array(rows)


TEMPLATE_LABELS, TEMPLATE_MATRIX = _templates()


def recognize_chords(y: np.ndarray, sr: int) -> list[ChordSpan]:
    if len(y) < sr // 4:
        return []
    hop = 512
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop)
    rms = librosa.feature.rms(y=y, hop_length=hop)[0]
    n = min(chroma.shape[1], len(rms))
    chroma, rms = chroma[:, :n], rms[:n]
    frame_times = librosa.frames_to_time(np.arange(n), sr=sr, hop_length=hop)

    seg_frames = max(1, int(round(SEGMENT * sr / hop)))
    spans: list[ChordSpan] = []
    for i in range(0, n, seg_frames):
        j = min(n, i + seg_frames)
        t0, t1 = float(frame_times[i]), float(frame_times[j - 1] + hop / sr)
        if np.mean(rms[i:j]) < SILENCE_RMS_REL * (np.max(rms) + 1e-9):
            spans.append(ChordSpan("N", t0, t1, 0.0))
            continue
        # RMS-weight the average so a segment's attack outweighs its decay tail
        w = rms[i:j] + 1e-9
        v = chroma[:, i:j] @ w / w.sum()
        v = v / (np.linalg.norm(v) + 1e-9)
        sims = TEMPLATE_MATRIX @ v
        best = int(np.argmax(sims))
        best = _prefer_triad_on_ties(best, sims)
        label = TEMPLATE_LABELS[best] if sims[best] >= MIN_SIMILARITY else "N"
        if spans and spans[-1].label not in ("N", label):
            prev_sim = float(sims[TEMPLATE_LABELS.index(spans[-1].label)])
            if prev_sim >= float(sims[best]) - SWITCH_MARGIN and prev_sim >= MIN_SIMILARITY:
                label, best = spans[-1].label, TEMPLATE_LABELS.index(spans[-1].label)
        spans.append(ChordSpan(label, t0, t1, float(sims[best])))

    return _merge(spans)


def _base_triad(label: str) -> str | None:
    """Am7 → Am, Cmaj7 → C, A7 → A; None if not a 7th label."""
    if label.endswith("maj7"):
        return label[:-4]
    if label.endswith("m7"):
        return label[:-1]
    if label.endswith("7"):
        return label[:-1]
    return None


SEVENTH_MARGIN = 0.02


def _prefer_triad_on_ties(best: int, sims: np.ndarray) -> int:
    """A 7th chord must clearly beat its own base triad. Note attacks are
    harmonic-rich (the third's 3rd harmonic IS the major 7th), which nudges 7th
    templates ahead by a hair on plain triads."""
    base = _base_triad(TEMPLATE_LABELS[best])
    if base is None:
        return best
    base_idx = TEMPLATE_LABELS.index(base)
    if float(sims[base_idx]) >= float(sims[best]) - SEVENTH_MARGIN:
        return base_idx
    return best


def _merge(spans: list[ChordSpan]) -> list[ChordSpan]:
    merged: list[ChordSpan] = []
    for s in spans:
        if merged and merged[-1].label == s.label:
            prev = merged[-1]
            # length-weighted running mean of similarity
            w1, w2 = prev.end - prev.start, s.end - s.start
            sim = (prev.similarity * w1 + s.similarity * w2) / max(w1 + w2, 1e-9)
            merged[-1] = ChordSpan(prev.label, prev.start, s.end, round(sim, 3))
        else:
            merged.append(s)
    return [ChordSpan(s.label, round(s.start, 3), round(s.end, 3), round(s.similarity, 3))
            for s in merged]


def render_chart(spans: list[ChordSpan]) -> str:
    """Human-readable chord chart with timings."""
    lines = []
    for s in spans:
        if s.label == "N":
            continue
        lines.append(f"{s.start:7.2f}s – {s.end:7.2f}s   {s.label:<4} "
                     f"(match {s.similarity:.0%})")
    return "\n".join(lines) if lines else "(no confident chords detected)"
