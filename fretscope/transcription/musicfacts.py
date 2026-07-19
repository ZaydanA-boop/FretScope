"""Quick song facts a guitarist actually wants: key, tempo, tuning offset.

Plain English:
- **Key**: which scale the song lives in ("A minor"). Found by comparing the
  song's overall note-usage fingerprint against the classic major/minor key
  profiles (Krumhansl-Schmuckler) — the standard textbook method.
- **Tempo**: beats per minute, from the onset rhythm.
- **Tuning**: whether the recording sits above/below standard pitch. Old records
  and down-tuned bands are often 20-50 cents off; knowing saves you a confusing
  practice session. Reported in cents (100 cents = one fret).

All heuristic-grade: good first answers, not gospel. Key detection especially
gets confused by key changes and heavy distortion.
"""

from __future__ import annotations

from dataclasses import dataclass

import librosa
import numpy as np

PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Krumhansl-Kessler key profiles (major / minor), C-rooted.
_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09,
                   2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53,
                   2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


@dataclass
class SongFacts:
    key: str              # e.g. "A minor"
    key_confidence: float  # 0..1 correlation margin over runner-up
    tempo_bpm: float
    tuning_cents: float   # + = sharp of A440, − = flat

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "key_confidence": round(self.key_confidence, 2),
            "tempo_bpm": round(self.tempo_bpm, 1),
            "tuning_cents": round(self.tuning_cents, 1),
            "confidence": "heuristic",
        }


def analyze_facts(y: np.ndarray, sr: int) -> SongFacts:
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    profile = chroma.mean(axis=1)

    scores: list[tuple[float, str]] = []
    for root in range(12):
        rolled = np.roll(profile, -root)
        for name, template in (("major", _MAJOR), ("minor", _MINOR)):
            r = float(np.corrcoef(rolled, template)[0, 1])
            scores.append((r, f"{PITCH_CLASSES[root]} {name}"))
    scores.sort(reverse=True)
    best_r, best_key = scores[0]
    margin = max(0.0, best_r - scores[1][0])

    tempo = librosa.feature.tempo(y=y, sr=sr)
    tempo_bpm = float(tempo[0]) if len(tempo) else 0.0

    tuning = float(librosa.estimate_tuning(y=y, sr=sr))  # fraction of a semitone

    return SongFacts(key=best_key,
                     key_confidence=min(1.0, margin * 5),
                     tempo_bpm=tempo_bpm,
                     tuning_cents=tuning * 100)
