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
- End-to-end verified 2026-07-18: real Demucs separation on a synthetic
  guitar+bass+drums mix returned a stem that transcribed to exactly the guitar
  melody; a live YouTube link ran the full download→separate→transcribe→tone→report
  path through the dashboard API.
- GitHub remote: not yet created (gh CLI needs interactive auth). Commands to run
  are at the bottom of this file.
- 2026-07-18 second pass (project rethink with user): added the three-way tone
  upgrade — tone timeline, learned parameter model, closed-loop tone matching.
  See "Tone system v2" below.

## Tone system v2 (timeline + learned model + matching)

One windowed feature engine, three consumers:

| Piece | Module | What it does |
|---|---|---|
| Tone timeline | `tone/timeline.py` | cheap windowed features → change-point detection → per-section full analysis; sections merged when the drive category doesn't change |
| Learned mapper | `tone/learned.py`, `tone/train.py` | random forest trained on ~700 synthesized clips through pedalboard chains with KNOWN settings; predicts drive dB, reverb wet/room, delay time/mix, each shipped with its held-out MAE. Model committed at `tone/models/tone_model.joblib` (3.2 MB); regenerate with `python -m fretscope.tone.train` (needs `pedalboard`, dev extra) |
| Tone match | `tone/match.py`, `POST /api/jobs/{id}/match` | user records/uploads their attempt; feature deltas vs the song (or a timeline section) become directional advice ("add drive slightly", "shorten reverb") |

Key facts:
- Model MAE (held-out, current model): drive ±2.6 dB, reverb wet ±0.13, room ±0.25
  (weak), delay ±0.16 s, delay mix ±0.11, chorus rate ±0.5 Hz, chorus mix ±0.12.
  Displayed with every prediction.
- **Chorus is model-only.** Three hand-crafted detectors (spectral-centroid wobble,
  per-bin envelope modulation, cepstral delay tracking) all failed to separate
  chorus from note-rate structure on synthetic tests. The random forest DOES
  separate it (validated experiment: predicted mix 0.41 when present vs 0.09 when
  absent) using the two `subband_mod_*` features jointly with the rest. Never
  add a rule-based chorus card; the chain's chorus entry exists only when the
  model is installed and predicts mix ≥ 0.15.
- Training domain is synthesized Karplus-Strong guitar + pedalboard effects, NOT
  real amps — documented in learned.py docstring and in the UI strip.
- Everything degrades gracefully without the model file (predict_params → None).
- Reverb/sustain ambiguity: when the decay estimate maxes out (6 s) on a heavily
  driven signal, the chain reports "reverb (uncertain)" instead of claiming a hall
  — distortion sustain and big reverb are indistinguishable there.
- 2026-07-18 audit pass (user-directed "find every flaw"): input is trimmed to
  MAX_ANALYSIS_SECONDS (150 s) BEFORE Demucs so CPU separation never processes
  audio the analysis discards; YouTube downloads are capped at 20 minutes
  (MAX_YOUTUBE_MINUTES) and stream progress % into the stage log; merged timeline
  segments are re-analyzed over their full span instead of keeping the first
  half's features; POST /api/jobs/upload enables drag-and-drop local files
  (stored under jobs/uploads/); /api/health reports model_available; finished
  reports render once per job (re-rendering on poll ticks was resetting the stem
  player); static assets carry ?v= cache-busting (bump on every web/ change!).
- 2026-07-18 third pass (user-directed one-shot: "improve everything, app-like UI,
  lay-friendly"): see "Engine v3 + Dashboard v4" below.
- Dashboard v3 (same day): full charcoal retheme — neutral zinc surfaces, amber
  is the ONLY warm element (user: "charcoal based rather than brown"). App-shell
  layout (fixed topbar with status chips, scrollable library rail, sticky
  section tabs with scroll-spy over Tone/Match/Rig/Notes/Data), toasts,
  drag-drop zone, relative timestamps, hover-revealed delete.
- Dashboard (v2, 2026-07-18, user-directed redesign): tone match promoted to the
  top with bipolar delta bars per aspect; pedal cards and amp EQ render SVG rotary
  knobs (needle animates on scope change; static under prefers-reduced-motion);
  timeline strip always renders with a time ruler (with a "re-analyze" note for
  pre-timeline reports); chord charts collapsed behind a details toggle (user
  found them bulky) with a "Mostly Am, C, F" one-liner instead; clickable timeline
  scopes the rig knobs AND the match target. Reports written before the
  subband-feature change still work (features_from_dict fills defaults).

## Engine v3 + Dashboard v4 (2026-07-18 third pass)

Engine:
- Tone model retrained on 1400 clips with HARDER synthesis (palm-mute↔ringing
  decay, random tone-knob lowpass, strums+riffs) and a new pedalboard Compressor
  in the chains → new target comp_ratio (MAE ±1.2 over 1-8 range). MAEs went UP
  vs the 700-clip model (drive ±3.5 dB vs ±2.6) because the held-out set is now
  harder/more varied — that's more honest, not worse. Don't "fix" by removing
  synthesis variety.
- FRETSCOPE_DEMUCS_SHIFTS env (default 0): Demucs shift-trick averaging, each
  shift ≈ proportional slowdown for a small quality gain. htdemucs_ft documented
  as the slow/high-quality 4-stem alternative.
- 7th-chord templates (7, maj7, m7) with two guards: 0.94 template weight AND a
  7th must beat its own base triad by >0.02 similarity (string harmonics put the
  major-7th ON plain triads — the third's 3rd harmonic IS the maj7).
- transcription/musicfacts.py: key (Krumhansl-Schmuckler), tempo, tuning-offset
  → report["facts"], shown as chips + in markdown. All heuristic-labeled.

Dashboard v4 (app-like, lay-friendly):
- Section tabs moved into the TOPBAR (hidden unless a report is open); sidebar
  collapsible via hamburger (persisted in localStorage); "New analysis" is a
  collapsible details card.
- Stem player is a slim full-width pill bar under the title, no longer crammed
  beside it.
- Chord parts render as real SVG chord diagrams (OPEN_SHAPES dict + computed
  E/A-shape barre fallbacks, finger numbering with barre detection) with "% of
  the song"; timed chart stays behind a toggle.
- Rig looks like a pedalboard: per-effect muted hues (--ph custom property),
  LED, footswitch, white knobs on colored enclosures, board background strip.
- Lay-language sweep: measurements renamed (spikiness, ring-out time, dark↔bright
  lean) with tooltip explanations; pedal evidence lives behind a "why this
  guess?" tooltip; classification notes are plain sentences (rationale in title
  attr). Keep this register in future copy.

## Lyrics + Dashboard v5 (2026-07-18 fourth pass)

- Lyrics: separation now also saves the vocals stem; `lyrics.py` transcribes it
  with faster-whisper (base model, CPU int8, VAD-filtered; env
  FRETSCOPE_WHISPER_MODEL) and each line gets the chord sounding at its
  midpoint. Degrades to nothing without faster-whisper/vocals/singing. The
  `[lyrics]` extra documents the dep; it IS installed in this venv.
- The wall-of-timestamps chord chart is GONE. Replaced by a chord ribbon
  synced to the stem player (timeupdate highlights the playing chord; click to
  seek) and clickable lyric lines that also seek.
- Topbar tabs are now a little guitar: SVG headstock + body outlines, tabs as
  fret-separated segments on the neck, line icons above each label.
- Health chips only render when something is BROKEN (user: remove the green
  chips). Sidebar collapse animates as a drawer (grid-column transition,
  contents keep width). Panel content is centered (user preference); tab/pre
  blocks stay left-aligned inside centered containers.
- Collision fixes: chord-diagram position label ("2fr") moved to the LEFT of
  the grid with text-anchor=end; pedal "why this guess?" is in normal flow
  (was absolutely positioned over settings); pedal text wraps with
  overflow-wrap; h3 padded clear of the LED.

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
- **Demucs htdemucs_6s, dedicated "guitar" stem** (upgraded 2026-07-18 after the user
  found 4-stem "other" isolation poor). The 6-source model extracts guitar
  specifically; if the guitar stem holds <10% of guitar+other energy the two are
  blended (model misfiled the guitar) and the report says so. Switchable via
  FRETSCOPE_SEPARATION_MODEL. No model separates lead from rhythm guitar — surfaced
  in every report. Next rungs if still not good enough: Mel-Band Roformer guitar
  checkpoints via the audio-separator package (better quality, ~10-20 min/song on
  this CPU), or commercial APIs (Moises/LALAL/AudioShake).
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

## Pushing to GitHub (one-time setup)

```powershell
gh auth login          # pick GitHub.com → HTTPS → login with browser
gh repo create fretscope --private --source . --push
```

(`gh` was installed via winget; open a fresh terminal so it's on PATH.)
