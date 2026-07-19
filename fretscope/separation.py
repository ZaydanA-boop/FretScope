"""Stem separation: pull the guitar out of the mix.

Plain English: source-separation models can un-mix a song into its instruments.
The default model here (Demucs htdemucs_6s) has a stem trained specifically for
guitar. That is much closer to "just the guitar" than the older 4-stem approach
(where guitar shared an "everything else" bucket with keys, synths and strings),
but it is still the acknowledged weak point of the model family: expect some
leakage in and out. And no model, commercial or open, can split two guitars
playing at once — simultaneous lead and rhythm arrive glued together. That
limitation is reported, not hidden.

Safety net: on some songs the dedicated guitar stem comes back nearly silent even
though there is clearly guitar in the mix (the model shoved it into "other").
When the guitar stem holds too little of the non-vocal/drum/bass energy, we blend
guitar + other and say so.

Demucs (and torch) are optional heavy dependencies. Without them, separation is
skipped: the full mix goes downstream and the result is flagged so every report
says transcription/tone ran on the whole song, not an isolated guitar.

Models, switchable via FRETSCOPE_SEPARATION_MODEL:
    htdemucs_6s (default)  6 stems incl. dedicated guitar
    htdemucs               4 stems; guitar lives in "other"
    htdemucs_ft            fine-tuned 4-stem, better quality, ~4x slower

Quality/compute dial: FRETSCOPE_DEMUCS_SHIFTS (default 0). Demucs' "shift
trick" averages predictions over N random time-shifts of the input; each shift
buys a little quality for a proportional slowdown (per the official docs).
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import ANALYSIS_SR
from .audio_io import ensure_ffmpeg_on_path, load_audio, save_wav

DEFAULT_MODEL = "htdemucs_6s"

# If the guitar stem carries less than this share of the combined guitar+other
# energy, the model probably misfiled the guitar; blend the two stems instead.
GUITAR_MIN_ENERGY_SHARE = 0.10


def _model_name() -> str:
    return os.environ.get("FRETSCOPE_SEPARATION_MODEL", DEFAULT_MODEL)


@dataclass
class SeparationResult:
    """What downstream stages receive."""

    audio: np.ndarray            # mono float32 at ANALYSIS_SR
    sr: int
    separated: bool              # True if a real model produced this stem
    stem_name: str               # "guitar", "guitar+other", "other", or "full_mix"
    method: str                  # e.g. "demucs/htdemucs_6s" or "none"
    notes: list[str] = field(default_factory=list)
    stem_path: Path | None = None


LIMITATION_NOTE = (
    "The guitar stem comes from a model trained to extract guitar specifically, "
    "but some leakage of keys/synths (in) or guitar (out) is normal. Simultaneous "
    "lead and rhythm guitar are NOT separated from each other — no current model "
    "can do that."
)

BLEND_NOTE = (
    "The dedicated guitar stem came back nearly empty, so guitar was blended with "
    "the 'other' stem (keys/synths/strings included) to avoid losing the part."
)

OTHER_ONLY_NOTE = (
    "This model has no dedicated guitar stem: all guitars (plus keys, synths, "
    "strings) share one 'other' stem."
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

    With demucs installed: run the configured model and keep its guitar stem
    (blending with 'other' if the guitar stem is suspiciously empty).
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

    model_name = _model_name()
    if progress:
        progress(f"loading Demucs model {model_name} (first run downloads weights)")

    ensure_ffmpeg_on_path()  # demucs AudioFile shells out to ffmpeg/ffprobe by name
    import torch
    from demucs.apply import apply_model
    from demucs.audio import AudioFile
    from demucs.pretrained import get_model

    model = get_model(model_name)
    model.eval()

    wav = AudioFile(src_wav).read(streams=0, samplerate=model.samplerate,
                                  channels=model.audio_channels)
    ref = wav.mean(0)
    wav = (wav - ref.mean()) / (ref.std() + 1e-8)

    shifts = int(os.environ.get("FRETSCOPE_DEMUCS_SHIFTS", "0") or 0)
    if progress:
        progress("separating stems with Demucs (CPU — this can take a few minutes)"
                 + (f", averaging {shifts + 1} shifted passes" if shifts else ""))
    with torch.no_grad():
        sources = apply_model(model, wav[None], device="cpu", progress=False,
                              shifts=shifts, overlap=0.25)[0]
    sources = sources * (ref.std() + 1e-8) + ref.mean()

    stems = {name: s.mean(0).cpu().numpy().astype(np.float32)
             for name, s in zip(model.sources, sources)}

    stem, stem_name, notes = _pick_guitar_stem(stems)

    # Resample the stem to the analysis rate via our ffmpeg path
    raw_path = work_dir / "stem_raw.wav"
    save_wav(raw_path, stem, sr=model.samplerate)
    y, sr = load_audio(raw_path, sr=ANALYSIS_SR)
    stem_path = save_wav(work_dir / "guitar_stem.wav", y, sr=sr)
    raw_path.unlink(missing_ok=True)

    return SeparationResult(
        audio=y, sr=sr, separated=True, stem_name=stem_name,
        method=f"demucs/{model_name}", notes=notes, stem_path=stem_path,
    )


def _pick_guitar_stem(stems: dict[str, np.ndarray]) -> tuple[np.ndarray, str, list[str]]:
    """Choose what to hand downstream from the model's stems."""
    if "guitar" not in stems:
        return stems["other"], "other", [OTHER_ONLY_NOTE]

    guitar = stems["guitar"]
    other = stems.get("other")
    if other is None:
        return guitar, "guitar", [LIMITATION_NOTE]

    e_guitar = float(np.sum(guitar.astype(np.float64) ** 2))
    e_other = float(np.sum(other.astype(np.float64) ** 2))
    share = e_guitar / (e_guitar + e_other + 1e-12)
    if share < GUITAR_MIN_ENERGY_SHARE:
        return guitar + other, "guitar+other", [BLEND_NOTE, LIMITATION_NOTE]
    return guitar, "guitar", [LIMITATION_NOTE]
