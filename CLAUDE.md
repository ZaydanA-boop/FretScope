# CLAUDE.md — FretScope project brief for Claude sessions

**Read `docs/SOP.md` before touching code.** It's the working agreement with the user.

## Purpose

Take a song (YouTube link or local audio), isolate the guitar, and produce:
1. Tab (lead/monophonic) or chord chart (rhythm/chordal), and
2. A tone breakdown (gain/distortion, reverb, EQ, compression) with suggested amp/pedal
   starting settings — always labeled as estimates.

The user feeds in YouTube links and views results in a custom web dashboard.

## Current status

- Phase 1 (scaffold: env, audio I/O, tests) — done
- Phase 2 (stem separation) — done
- Phase 3 (transcription: notes→tab, chords) — done
- Phase 4 (tone feature extraction) — done
- Phase 5 (recreation mapping) — done
- Phase 6 (report output) — done
- Dashboard (FastAPI + web UI) — done

## Environment (this machine)

- Windows 11, PowerShell. System Python is **3.14** — too new for the audio ML stack.
  The project venv at `.venv/` uses **Python 3.12**
  (`C:\Users\Zaydan Ahmed\AppData\Local\Programs\Python\Python312\python.exe`), installed via winget.
- ffmpeg installed via winget (Gyan.FFmpeg). `fretscope.audio_io.find_ffmpeg()` searches
  PATH, then `FRETSCOPE_FFMPEG`, then the WinGet Links folder — don't assume it's on PATH
  in a fresh shell.
- Demucs/torch live behind the `[separation]` extra and are imported lazily; everything
  else must work (and all tests must pass) without them.

## Architecture

`fretscope/` package:

| Module | Role |
|---|---|
| `audio_io.py` | ffmpeg discovery, YouTube download (yt-dlp), decode to mono float32 WAV |
| `separation.py` | Demucs wrapper → "other" stem; graceful fallback when torch absent |
| `transcription/classify.py` | lead vs rhythm decision (polyphony estimate via chroma flatness) |
| `transcription/pitch.py` | pYIN pitch track + onsets → `Note` list |
| `transcription/fretting.py` | pitch → (string, fret) via playability cost minimization |
| `transcription/tab.py` | `Note`+fretting → ASCII tab |
| `transcription/chords.py` | chroma → chord template matching → timed chord chart |
| `tone/features.py` | distortion/EQ/reverb/compression feature extraction |
| `tone/mapping.py` | features → effect-chain estimate + parameter ranges |
| `report.py` | assemble JSON + markdown report |
| `pipeline.py` | orchestrates the whole run, records per-stage status/confidence |
| `cli.py` | `fretscope analyze`, `fretscope serve` |
| `server/app.py` | FastAPI: job submit (YouTube URL/file), status polling, results, static dashboard |
| `server/jobs.py` | background job runner (thread-based), job state on disk under `jobs/` |
| `web/` | dashboard (vanilla HTML/CSS/JS, no build step) |

## Key decisions and why

- **Python 3.12 venv, not system 3.14** — numba/librosa/torch wheel availability.
- **Demucs, "other" stem** — best available open model; it does NOT separate lead from
  rhythm guitar. This limitation is surfaced in every report rather than hidden.
- **Separation is optional** (`[separation]` extra, lazy import) so the core pipeline,
  tests, and dashboard work on machines without torch. Without it, analysis runs on the
  full mix and the report says so (confidence downgraded).
- **pYIN for pitch** (librosa) — monophonic only, but robust and dependency-light. No
  CREPE/basic-pitch because they drag in TensorFlow.
- **Fretting heuristic**: minimize total cost = fret-position movement between consecutive
  notes + open-string bonus + high-fret penalty, via per-note greedy DP over the 6 standard-
  tuning strings, 0–19 frets. Documented as *one* playable interpretation.
- **Chord recognition**: beat-synchronous chroma vs. 24 major/minor triad templates (+ N
  no-chord). Simple, explainable; no 7ths/inversions yet.
- **Tone analysis is feature→category mapping, never device identification.** Categories:
  gain/distortion (via harmonic distortion proxy + crest factor), EQ character (octave-band
  tilt vs. reference), reverb (decay-tail estimate), compression (dynamic-range stats),
  modulation hint (spectral flux periodicity). Output labels: `estimated` only.
- **Dashboard has no build step** (vanilla JS) so it runs anywhere the Python server runs.
- **Confidence labels** (`verified` / `heuristic` / `estimated`) attached per report section
  — see SOP for definitions.

## Known limitations

- Lead + rhythm guitar playing simultaneously are not separable; report flags it.
- pYIN transcription degrades on distorted/polyphonic lead tone; bends/slides/vibrato are
  not detected (notes only).
- Chord charts: major/minor triads only; no key detection, no 7th chords.
- Tone mapping is calibrated on synthetic tests + reasoning, not a labeled pedal dataset —
  ranges are starting points, not measurements of the original rig.
- Demucs on CPU is slow (minutes per song). Job runner streams stage progress to the UI.
- YouTube download depends on yt-dlp keeping up with YouTube; failures surface in job log.

## Conventions

- One commit per phase/feature, message explains *why* (see SOP).
- Tests use synthesized audio (numpy sine/chord fixtures in `tests/conftest.py`) — no
  copyrighted audio in the repo, no network in tests.
- All user-facing numbers from tone analysis carry a range, not a point value.
