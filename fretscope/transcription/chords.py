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


def _templates() -> tuple[list[str], np.ndarray]:
    labels, rows = [], []
    for root in range(12):
        for quality, intervals in (("", (0, 4, 7)), ("m", (0, 3, 7))):
            v = np.zeros(12)
            v[[(root + i) % 12 for i in intervals]] = 1.0
            labels.append(PITCH_CLASSES[root] + quality)
            rows.append(v / np.linalg.norm(v))
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
        label = TEMPLATE_LABELS[best] if sims[best] >= MIN_SIMILARITY else "N"
        if spans and spans[-1].label not in ("N", label):
            prev_sim = float(sims[TEMPLATE_LABELS.index(spans[-1].label)])
            if prev_sim >= float(sims[best]) - SWITCH_MARGIN and prev_sim >= MIN_SIMILARITY:
                label, best = spans[-1].label, TEMPLATE_LABELS.index(spans[-1].label)
        spans.append(ChordSpan(label, t0, t1, float(sims[best])))

    return _merge(spans)


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
