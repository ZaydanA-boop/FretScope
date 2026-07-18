"""Monophonic pitch tracking: audio → a list of timed notes.

Plain English: we trace the fundamental pitch of the melody moment by moment (pYIN),
find where new notes begin (onset detection), and collapse each span between onsets
to a single note — its pitch, start time, and length.

pYIN is monophonic: it follows ONE pitch. On chordal audio it will jump between the
strongest notes and produce garbage — that's why classify.py routes chordal parts to
chord recognition instead.
"""

from __future__ import annotations

from dataclasses import dataclass

import librosa
import numpy as np


@dataclass
class Note:
    midi: int
    start: float          # seconds
    duration: float       # seconds
    confidence: float     # mean voiced-probability over the note's frames

    @property
    def name(self) -> str:
        return librosa.midi_to_note(self.midi, unicode=False)


FMIN = librosa.note_to_hz("D2")   # a step below standard-tuning low E, allows drop-D
FMAX = librosa.note_to_hz("E6")   # 24th fret on the high E string
MIN_NOTE_DUR = 0.06               # ignore blips shorter than ~a 32nd at 120 bpm


def extract_notes(y: np.ndarray, sr: int, hop_length: int = 256) -> list[Note]:
    if len(y) < sr // 8:
        return []

    f0, voiced_flag, voiced_prob = librosa.pyin(
        y, fmin=FMIN, fmax=FMAX, sr=sr, hop_length=hop_length, fill_na=np.nan,
    )
    times = librosa.times_like(f0, sr=sr, hop_length=hop_length)

    onsets = librosa.onset.onset_detect(
        y=y, sr=sr, hop_length=hop_length, units="time", backtrack=True,
    )
    # Segment boundaries: every onset, plus start and end of the clip
    bounds = np.unique(np.concatenate([[0.0], onsets, [times[-1] + 1e-3]]))

    notes: list[Note] = []
    for t0, t1 in zip(bounds[:-1], bounds[1:]):
        sel = (times >= t0) & (times < t1) & voiced_flag & ~np.isnan(f0)
        if sel.sum() < 2:
            continue
        # Median is robust to pitch-tracker glitches at note edges
        hz = float(np.median(f0[sel]))
        conf = float(np.nanmean(voiced_prob[sel]))
        # Trim the note to its actually-voiced span inside the segment
        seg_times = times[sel]
        start, end = float(seg_times[0]), float(seg_times[-1])
        if end - start < MIN_NOTE_DUR:
            continue
        notes.append(Note(midi=int(round(librosa.hz_to_midi(hz))),
                          start=round(start, 3),
                          duration=round(end - start, 3),
                          confidence=round(conf, 3)))
    return _merge_repeats(notes)


def _merge_repeats(notes: list[Note], gap: float = 0.03) -> list[Note]:
    """Merge same-pitch fragments the onset detector split spuriously.

    Two touching segments with the same pitch and no real gap are one held note.
    (A genuinely re-picked note produces a gap or an onset with an energy burst;
    this only merges segments closer than `gap` seconds.)
    """
    merged: list[Note] = []
    for n in notes:
        if merged and merged[-1].midi == n.midi and \
                n.start - (merged[-1].start + merged[-1].duration) <= gap:
            prev = merged[-1]
            merged[-1] = Note(prev.midi, prev.start,
                              round(n.start + n.duration - prev.start, 3),
                              max(prev.confidence, n.confidence))
        else:
            merged.append(n)
    return merged
