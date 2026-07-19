"""Shared audio fixtures for the test suite.

No copyrighted recordings ship with this repo: tests synthesize their own signals.
The pluck fixture uses Karplus-Strong synthesis — a feedback delay line that sounds
convincingly like a plucked string and, importantly for tests, has a real harmonic
series and a natural decay like a guitar note.
"""

from __future__ import annotations

import numpy as np
import pytest

from fretscope import ANALYSIS_SR

SR = ANALYSIS_SR


def karplus_strong(freq: float, dur: float, sr: int = SR, decay: float = 0.996,
                   seed: int = 7) -> np.ndarray:
    """Synthesize one plucked-string note."""
    rng = np.random.default_rng(seed)
    n = int(sr * dur)
    period = max(2, int(round(sr / freq)))
    buf = rng.uniform(-1, 1, period)
    out = np.empty(n, dtype=np.float64)
    for i in range(n):
        out[i] = buf[i % period]
        buf[i % period] = decay * 0.5 * (buf[i % period] + buf[(i + 1) % period])
    return (out / (np.max(np.abs(out)) + 1e-9)).astype(np.float32)


def note_sequence(freqs: list[float], note_dur: float = 0.4, sr: int = SR) -> np.ndarray:
    """Concatenate plucked notes into a monophonic 'lead line'."""
    return np.concatenate([karplus_strong(f, note_dur, sr, seed=i)
                           for i, f in enumerate(freqs)]).astype(np.float32)


def chord(freqs: list[float], dur: float, sr: int = SR) -> np.ndarray:
    """Sum of plucked strings starting together — a strummed chord, roughly."""
    voices = [karplus_strong(f, dur, sr, seed=i + 100) for i, f in enumerate(freqs)]
    y = np.sum(voices, axis=0)
    return (y / (np.max(np.abs(y)) + 1e-9)).astype(np.float32)


# Frequencies (Hz), standard tuning references
E2, A2, D3, G3, B3, E4 = 82.41, 110.0, 146.83, 196.0, 246.94, 329.63
A4, C4, E5, G4, C5 = 440.0, 261.63, 659.25, 392.0, 523.25


@pytest.fixture(scope="session")
def lead_line() -> np.ndarray:
    """A pentatonic-ish monophonic phrase: A3 C4 D4 E4 G4 A4."""
    return note_sequence([220.0, 261.63, 293.66, 329.63, 392.0, 440.0])


@pytest.fixture(scope="session")
def a_minor_chord() -> np.ndarray:
    """A minor triad voiced like an open Am: A2 E3 A3 C4 E4."""
    return chord([110.0, 164.81, 220.0, 261.63, 329.63], dur=2.0)


@pytest.fixture(scope="session")
def c_major_chord() -> np.ndarray:
    """C major: C3 E3 G3 C4 E4."""
    return chord([130.81, 164.81, 196.0, 261.63, 329.63], dur=2.0)


@pytest.fixture(scope="session")
def sine_a4() -> np.ndarray:
    t = np.arange(int(SR * 1.0)) / SR
    return (0.5 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
