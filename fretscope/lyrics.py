"""Lyric transcription from the separated vocals stem, with chords attached.

Plain English: Demucs already hands us the vocals on their own track. We run a
small speech-recognition model (faster-whisper, on CPU) over that track to get
timed lyric lines, then label each line with whichever chord the guitar was
holding at that moment. Result: a play-along sheet — chords above words.

Reality checks, stated up front:
- Sung words are harder than spoken words; expect mondegreens, especially with
  heavy effects or screaming. Label: heuristic.
- The chord attached to a line is the chord sounding at the line's midpoint —
  fine for strummed songs, blurry when chords change mid-line.
- Everything degrades gracefully: no faster-whisper installed, no vocals stem,
  or an instrumental → no lyrics section, nothing breaks.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

WHISPER_MODEL = os.environ.get("FRETSCOPE_WHISPER_MODEL", "base")
MIN_LINE_CHARS = 2
MAX_LINES = 80


def lyrics_available() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None


def transcribe_lyrics(vocals_path: Path | str, progress=None) -> list[dict]:
    """Timed lyric lines from a vocals WAV: [{start, end, text}, ...]."""
    if not lyrics_available():
        return []
    from faster_whisper import WhisperModel

    if progress:
        progress(f"listening to the vocal (whisper {WHISPER_MODEL}, first run "
                 "downloads the speech model)")
    model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(str(vocals_path), vad_filter=True,
                                       beam_size=1)
    lines = []
    for seg in segments:
        text = seg.text.strip()
        if len(text) < MIN_LINE_CHARS:
            continue
        lines.append({"start": round(float(seg.start), 2),
                      "end": round(float(seg.end), 2),
                      "text": text})
        if len(lines) >= MAX_LINES:
            break
    return lines


def attach_chords(lines: list[dict], chords: list[dict]) -> list[dict]:
    """Label each lyric line with the chord sounding at its midpoint."""
    spans = [c for c in chords or [] if c.get("chord") not in (None, "N")]
    out = []
    for line in lines:
        mid = (line["start"] + line["end"]) / 2
        chord = next((c["chord"] for c in spans
                      if c["start"] <= mid < c["end"]), None)
        out.append({**line, "chord": chord})
    return out
