"""Stem separation: pull the guitar out of the mix.

Plain English: source-separation models can un-mix a song into vocals, drums, bass,
and "everything else". Guitars live in that "everything else" stem — along with keys,
synths, strings, and anything that isn't voice/drums/bass. So what we hand downstream
is "the guitar, plus whatever else was in that layer", and if a song has lead and
rhythm guitar at once, they arrive still glued together. That limitation is reported,
not hidden.

Demucs (and torch) are optional heavy dependencies. Without them, separation is
skipped: the full mix goes downstream and the result is flagged so every report says
transcription/tone ran on the whole song, not an isolated guitar.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import ANALYSIS_SR
from .audio_io import ensure_ffmpeg_on_path, load_audio, save_wav

DEMUCS_MODEL = "htdemucs"


@dataclass
class SeparationResult:
    """What downstream stages receive."""

    audio: np.ndarray            # mono float32 at ANALYSIS_SR
    sr: int
    separated: bool              # True if a real model produced this stem
    stem_name: str               # "other" (Demucs) or "full_mix"
    method: str                  # e.g. "demucs/htdemucs" or "none"
    notes: list[str] = field(default_factory=list)
    stem_path: Path | None = None


LIMITATION_NOTE = (
    "Demucs isolates vocals/drums/bass well, but all guitars (plus keys, synths, "
    "strings) share one 'other' stem. Simultaneous lead and rhythm guitar are NOT "
    "separated from each other."
)

FALLBACK_NOTE = (
    "Stem separation unavailable (demucs/torch not installed) — analysis ran on the "
    "FULL MIX. Vocals, drums and bass will contaminate transcription and tone "
    "estimates; treat results with extra skepticism or install the [separation] extra."
)


def separation_available() -> bool:
    return (importlib.util.find_spec("demucs") is not None
            and importlib.util.find_spec("torch") is not None)


def separate_guitar(src_wav: Path | str, work_dir: Path | str,
                    progress=None) -> SeparationResult:
    """Return the best-available 'guitar' audio for a song.

    With demucs installed: run htdemucs, keep the 'other' stem.
    Without: return the full mix, flagged as unseparated.
    """
    src_wav = Path(src_wav)
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    if not separation_available():
        y, sr = load_audio(src_wav)
        return SeparationResult(
            audio=y, sr=sr, separated=False, stem_name="full_mix", method="none",
            notes=[FALLBACK_NOTE],
        )

    if progress:
        progress("loading Demucs model (first run downloads ~80 MB of weights)")

    ensure_ffmpeg_on_path()  # demucs AudioFile shells out to ffmpeg/ffprobe by name
    import torch
    from demucs.apply import apply_model
    from demucs.audio import AudioFile
    from demucs.pretrained import get_model

    model = get_model(DEMUCS_MODEL)
    model.eval()

    wav = AudioFile(src_wav).read(streams=0, samplerate=model.samplerate,
                                  channels=model.audio_channels)
    ref = wav.mean(0)
    wav = (wav - ref.mean()) / (ref.std() + 1e-8)

    if progress:
        progress("separating stems with Demucs (CPU — this can take a few minutes)")
    with torch.no_grad():
        sources = apply_model(model, wav[None], device="cpu", progress=False)[0]
    sources = sources * (ref.std() + 1e-8) + ref.mean()

    stems = dict(zip(model.sources, sources))
    other = stems["other"].mean(0).cpu().numpy().astype(np.float32)

    # Resample the stem to the analysis rate via our ffmpeg path
    raw_path = work_dir / "other_raw.wav"
    save_wav(raw_path, other, sr=model.samplerate)
    y, sr = load_audio(raw_path, sr=ANALYSIS_SR)
    stem_path = save_wav(work_dir / "guitar_stem.wav", y, sr=sr)
    raw_path.unlink(missing_ok=True)

    return SeparationResult(
        audio=y, sr=sr, separated=True, stem_name="other",
        method=f"demucs/{DEMUCS_MODEL}", notes=[LIMITATION_NOTE],
        stem_path=stem_path,
    )
