"""Tone timeline: find where the guitar's tone *changes* within a song.

Plain English: a real song rarely has one tone. Verses are often clean, choruses
driven, solos boosted and delayed. Instead of averaging all of that into a single
estimate, we slide a window along the song, measure a small set of cheap tone
features per window, and look for moments where those features jump — that's a
tone change. Each resulting section then gets the full tone analysis on its own
audio.

Segmentation is a heuristic (label: heuristic); the per-section tone estimates
stay `estimated` like all tone output. Known failure modes: gradual swells don't
produce clean boundaries, and quiet breakdowns can read as "tone changes" when
only the level changed (we z-score features to soften, not eliminate, this).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import librosa
import numpy as np

from .features import BANDS, ToneFeatures, extract_tone_features
from .mapping import ToneEstimate, estimate_tone

WINDOW_S = 4.0        # seconds per analysis window
HOP_S = 2.0           # window hop
MIN_SEGMENT_S = 8.0   # never emit sections shorter than this
NOVELTY_STD = 1.0     # boundary when novelty exceeds mean + this many stds


@dataclass
class ToneSegment:
    start: float
    end: float
    features: ToneFeatures
    estimate: ToneEstimate
    label: str            # the segment's drive category, e.g. "clean", "overdrive"

    def to_dict(self) -> dict:
        return {
            "start": round(self.start, 2),
            "end": round(self.end, 2),
            "label": self.label,
            "features": self.features.to_dict(),
            "estimate": self.estimate.to_dict(),
            "confidence": "estimated",
        }


def _window_features(y: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """Cheap per-window feature matrix used only for boundary detection.

    No pitch tracking here (too slow to run per window); drive changes show up
    plainly in clipping ratio, crest factor, tilt and band balance.
    """
    win = int(WINDOW_S * sr)
    hop = int(HOP_S * sr)
    starts = np.arange(0, max(1, len(y) - win + 1), hop)
    rows, times = [], []
    for s in starts:
        seg = y[s: s + win]
        peak = float(np.max(np.abs(seg)) + 1e-9)
        rms = float(np.sqrt(np.mean(seg**2)) + 1e-9)
        crest = 20 * np.log10(peak / rms)
        flat_top = float(np.mean(np.abs(seg) > 0.98 * peak))
        S = np.abs(librosa.stft(seg, n_fft=2048))
        freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
        power = np.mean(S**2, axis=1)
        total = float(np.sum(power)) + 1e-12
        bands = [float(np.sum(power[(freqs >= lo) & (freqs < hi)])) / total
                 for lo, hi in BANDS.values()]
        sel = (freqs >= 100) & (freqs <= 8000) & (power > 0)
        tilt = float(np.polyfit(np.log2(freqs[sel]),
                                10 * np.log10(power[sel] + 1e-12), 1)[0])
        centroid = float(np.sum(freqs * power) / total)
        rows.append([20 * np.log10(rms), crest, flat_top, tilt, centroid, *bands])
        times.append(s / sr)
    return np.array(rows), np.array(times)


def _boundaries(feats: np.ndarray, times: np.ndarray) -> list[float]:
    """Change-points: peaks in the distance between neighbouring window groups."""
    if len(feats) < 4:
        return []
    z = (feats - feats.mean(axis=0)) / (feats.std(axis=0) + 1e-9)
    k = 2  # windows on each side of a candidate boundary
    novelty = np.zeros(len(z))
    for i in range(k, len(z) - k):
        novelty[i] = float(np.linalg.norm(z[i: i + k].mean(axis=0)
                                          - z[i - k: i].mean(axis=0)))
    thresh = novelty.mean() + NOVELTY_STD * novelty.std()
    bounds: list[float] = []
    min_gap = MIN_SEGMENT_S
    for i in range(k, len(z) - k):
        if novelty[i] < thresh:
            continue
        if novelty[i] < np.max(novelty[max(0, i - 2): i + 3]):  # local max only
            continue
        t = float(times[i])
        if all(abs(t - b) >= min_gap for b in bounds) and t >= min_gap:
            bounds.append(t)
    return bounds


def tone_timeline(y: np.ndarray, sr: int) -> list[ToneSegment]:
    """Split the song at tone changes and analyze each section separately."""
    duration = len(y) / sr
    if duration < 2 * MIN_SEGMENT_S:
        edges = [0.0, duration]
    else:
        feats, times = _window_features(y, sr)
        bounds = _boundaries(feats, times)
        edges = [0.0] + bounds + [duration]
        # drop a too-short final section into its predecessor
        if len(edges) >= 3 and edges[-1] - edges[-2] < MIN_SEGMENT_S:
            edges.pop(-2)

    from .learned import predict_params

    def analyze_span(t0: float, t1: float) -> ToneSegment | None:
        seg_audio = y[int(t0 * sr): int(t1 * sr)]
        try:
            f = extract_tone_features(seg_audio, sr)
        except ValueError:
            return None  # silent section; nothing to say about its tone
        est = estimate_tone(f, predict_params(f))
        return ToneSegment(start=t0, end=t1, features=f, estimate=est,
                           label=est.chain[0].effect)

    segments = [s for t0, t1 in zip(edges[:-1], edges[1:])
                if (s := analyze_span(t0, t1)) is not None]

    # A boundary with the same drive category on both sides was noise (often
    # just a level change). Merge — and RE-ANALYZE the merged span, so its
    # features describe the whole span rather than only its first half.
    changed = True
    while changed:
        changed = False
        merged: list[ToneSegment] = []
        for s in segments:
            if merged and merged[-1].label == s.label:
                combined = analyze_span(merged[-1].start, s.end)
                if combined is not None:
                    merged[-1] = combined
                changed = True
            else:
                merged.append(s)
        segments = merged
    return segments
