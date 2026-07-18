# FretScope — Guitar Tone & Tab Analyzer

Feed it a song (YouTube link or audio file). It isolates the guitar, transcribes what's being
played, and estimates *how it was made to sound* — then suggests amp/pedal settings to get you
close.

**What you get per song:**

1. **Tab or chord chart** — lead lines become ASCII tab; chordal parts become a chord chart
   with timings.
2. **Tone breakdown** — measured audio characteristics (gain/distortion, reverb, EQ shape,
   compression) mapped to effect *categories* and rough parameter ranges you can dial in on
   your own gear.

## Honest limitations (read this)

- **Guitar isolation** uses Demucs `htdemucs_6s`, which has a dedicated guitar stem. It is
  the weak stem of the model family: expect some leakage of keys/synths in and guitar out.
  If a song has lead and rhythm guitar at once, they will **not** be separated from each
  other — no current model can do that. The report flags this.
- **Tab output is one playable interpretation, not "the" tab.** The same pitch exists at
  several fretboard positions; we pick positions with a playability heuristic (documented in
  `CLAUDE.md`).
- **Tone analysis is an estimate, never an identification.** No method reliably identifies a
  specific pedal or amp from audio. We measure spectral/harmonic/temporal features and map
  them to effect categories ("heavy overdrive, mid-scooped, large-room reverb") with suggested
  starting settings. Every tone output is labeled `estimated`.

## Quickstart

```powershell
# from the repo root (Windows)
.venv\Scripts\activate
pip install -e .[dev]
# optional, heavy (torch): enables real stem separation
pip install -e .[separation]

# analyze a YouTube link end to end
fretscope analyze "https://www.youtube.com/watch?v=..." --out jobs/

# or a local file
fretscope analyze path\to\song.mp3 --out jobs/

# launch the dashboard (then open http://127.0.0.1:8321)
fretscope serve
```

`ffmpeg` must be on PATH (or set `FRETSCOPE_FFMPEG`). Tests: `pytest`.

## Architecture

```
audio in (YouTube / file)
   │  audio_io: yt-dlp + ffmpeg → mono WAV
   ▼
separation: Demucs → "other" stem (guitar + everything not vocals/drums/bass)
   ▼
classify: polyphony estimate → lead (monophonic) vs rhythm (chordal)
   ├─ lead   → pitch tracking (pYIN) → notes → fret placement heuristic → ASCII tab
   └─ rhythm → chroma → chord template matching → chord chart
   ▼
tone: feature extraction (distortion, EQ curve, reverb decay, compression…)
   ▼
mapping: features → effect chain estimate + parameter ranges (labeled as estimates)
   ▼
report: JSON + human-readable markdown → dashboard
```

See `CLAUDE.md` for current status and key decisions, `docs/SOP.md` for working conventions.
