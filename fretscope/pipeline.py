"""End-to-end analysis pipeline: source → separated stem → transcription + tone → report.

Each stage records its status; a stage failure degrades the report instead of
killing the run (per SOP: blockers are surfaced, not buried).
"""

from __future__ import annotations

import traceback
from pathlib import Path

from . import ANALYSIS_SR
from .audio_io import download_youtube, is_youtube_url, load_audio, save_wav, to_wav
from .report import build_report
from .separation import separate_guitar
from .tone.features import extract_tone_features
from .tone.mapping import estimate_tone
from .transcription.chords import recognize_chords, render_chart
from .transcription.classify import classify_part
from .transcription.fretting import assign_frets
from .transcription.pitch import extract_notes
from .transcription.tab import render_tab

# Analysis window: transcribing a whole song monophonically is noisy and slow;
# we analyze up to this many seconds (from the start of detected signal).
MAX_ANALYSIS_SECONDS = 150


def analyze(source: str, work_dir: Path | str, progress=None,
            use_separation: bool = True) -> dict:
    """Run the full pipeline. `source` is a YouTube URL or a local audio path.

    Returns the report dict (also written to work_dir/report.json by callers
    that want persistence).
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    stages: dict[str, dict] = {}

    def note_stage(name, status, detail=""):
        stages[name] = {"status": status, "detail": detail}
        if progress:
            progress(name, status, detail)

    # ---- ingest -------------------------------------------------------------
    meta = {"source": source}
    try:
        if is_youtube_url(source):
            note_stage("download", "running", "fetching audio from YouTube")
            audio_path, yt_meta = download_youtube(source, work_dir)
            meta.update(yt_meta)
            note_stage("download", "done", str(audio_path.name))
        else:
            audio_path = Path(source)
            meta["title"] = audio_path.stem
            note_stage("download", "done", "local file")
        note_stage("decode", "running", "decoding to mono WAV")
        wav_path = to_wav(audio_path, work_dir / "input.wav", sr=ANALYSIS_SR)
        note_stage("decode", "done")
    except Exception as e:
        note_stage("decode", "failed", f"{e}")
        return build_report(meta=meta, stages=stages, error=str(e))

    # ---- separation ---------------------------------------------------------
    note_stage("separation", "running", "isolating the guitar layer")
    try:
        if use_separation:
            sep = separate_guitar(wav_path, work_dir,
                                  progress=lambda msg: note_stage("separation",
                                                                  "running", msg))
        else:
            from .separation import SeparationResult
            y, sr = load_audio(wav_path)
            sep = SeparationResult(audio=y, sr=sr, separated=False,
                                   stem_name="full_mix", method="disabled",
                                   notes=["Separation disabled by user request."])
        note_stage("separation", "done",
                   f"method={sep.method}, stem={sep.stem_name}")
    except Exception as e:
        traceback.print_exc()
        y, sr = load_audio(wav_path)
        from .separation import SeparationResult
        sep = SeparationResult(audio=y, sr=sr, separated=False,
                               stem_name="full_mix", method="failed",
                               notes=[f"Separation failed ({e}); analysis ran on "
                                      "the full mix."])
        note_stage("separation", "failed", str(e))

    y, sr = sep.audio, sep.sr
    if len(y) > MAX_ANALYSIS_SECONDS * sr:
        y = y[: MAX_ANALYSIS_SECONDS * sr]
        stages["separation"]["detail"] += f" (analysis limited to first {MAX_ANALYSIS_SECONDS}s)"
    if sep.stem_path is None:
        sep.stem_path = save_wav(work_dir / "guitar_stem.wav", y, sr)

    # ---- classification + transcription ------------------------------------
    transcription: dict = {}
    try:
        note_stage("classify", "running", "lead line or chordal part?")
        part = classify_part(y, sr)
        note_stage("classify", "done", f"{part.kind} — {part.rationale}")

        if part.kind == "lead":
            note_stage("transcribe", "running", "tracking pitch → notes → tab")
            notes = extract_notes(y, sr)
            fretted = assign_frets(notes)
            transcription = {
                "kind": "lead",
                "confidence": "heuristic",
                "notes": [{"name": n.note.name, "midi": n.note.midi,
                           "start": n.note.start, "duration": n.note.duration,
                           "string": n.string, "fret": n.fret} for n in fretted],
                "tab": render_tab(fretted),
            }
            note_stage("transcribe", "done", f"{len(fretted)} notes")
        else:
            note_stage("transcribe", "running", "matching chord templates")
            spans = recognize_chords(y, sr)
            played = [s for s in spans if s.label != "N"]
            transcription = {
                "kind": "rhythm",
                "confidence": "heuristic",
                "chords": [{"chord": s.label, "start": s.start, "end": s.end,
                            "match": s.similarity} for s in spans],
                "chart": render_chart(spans),
            }
            note_stage("transcribe", "done", f"{len(played)} chord spans")
        transcription["classification"] = {
            "kind": part.kind, "confidence": round(part.confidence, 2),
            "rationale": part.rationale, "label": "heuristic",
        }
    except Exception as e:
        traceback.print_exc()
        note_stage("transcribe", "failed", str(e))
        transcription = {"kind": "unavailable", "error": str(e)}

    # ---- tone ---------------------------------------------------------------
    tone: dict = {}
    try:
        note_stage("tone", "running", "measuring tone features")
        features = extract_tone_features(y, sr)
        estimate = estimate_tone(features)
        tone = {"features": features.to_dict(), "estimate": estimate.to_dict(),
                "confidence": "estimated"}
        from .tone.learned import predict_params
        model_params = predict_params(features)
        if model_params:
            tone["model_estimate"] = {"params": model_params,
                                      "confidence": "estimated"}
        note_stage("tone", "running", "mapping tone changes across the song")
        from .tone.timeline import tone_timeline
        segments = tone_timeline(y, sr)
        timeline = []
        for s in segments:
            d = s.to_dict()
            seg_params = predict_params(s.features)
            if seg_params:
                d["model_params"] = seg_params
            timeline.append(d)
        tone["timeline"] = timeline
        detail = estimate.chain[0].effect
        if len(segments) > 1:
            detail += f", {len(segments)} tone sections"
        note_stage("tone", "done", detail)
    except Exception as e:
        traceback.print_exc()
        note_stage("tone", "failed", str(e))
        tone = {"error": str(e)}

    return build_report(
        meta=meta, stages=stages, separation=sep, transcription=transcription,
        tone=tone,
    )
