# Decision log

Why FretScope is built the way it is, including the approaches that failed.

## Separation

- **Demucs `htdemucs_6s` with the dedicated guitar stem.** The 4-stem model lumps
  guitar into "other" with keys/synths/strings; the 6-source model extracts guitar
  specifically. When the guitar stem holds <10% of guitar+other energy, the model
  probably misfiled the part, so the two stems are blended and the report says so.
  Model switchable via `FRETSCOPE_SEPARATION_MODEL`; `FRETSCOPE_DEMUCS_SHIFTS`
  exposes Demucs' shift-trick quality dial.
- **Input is trimmed to 150 s before separation.** Demucs on CPU is the expensive
  stage; it must never process audio the analysis will discard.
- **No model separates two guitars playing at once** (lead + rhythm). Neither open
  source nor commercial. Every report states this instead of hiding it.

## Transcription

- **pYIN for pitch** (librosa): monophonic only, but robust and dependency-light —
  no TensorFlow-based trackers.
- **Fretting is a cost model, not truth.** Same pitch exists at several fretboard
  positions; a Viterbi pass minimizes hand movement + high-fret penalty − open-string
  bonus. Output is labeled as *one playable interpretation*.
- **Chord recognition is template matching with two physics guards.** Beat-window
  chroma vs triad + 7th templates. A 7th label must beat its own base triad by a
  margin, because the third's 3rd harmonic *is* the major 7th — without the guard,
  every clean triad relabels itself a 7th at note attacks. Decay hysteresis keeps
  a fading chord from producing phantom changes (an Am tail with the C gone matches
  "A" as well as "Am").

## Tone analysis

- **Feature → category mapping, never device identification.** Nothing can name a
  pedal from audio; the report says "sounds like this category, try these ranges."
  A test fails if output ever phrases itself as identification.
- **The learned parameter model trains on data we synthesize.** ~1400 Karplus-Strong
  clips (palm-muted↔ringing, dark↔bright, riffs and strums) rendered through
  pedalboard chains with known settings; a random forest inverts features back to
  parameters (drive dB, reverb wet/room, delay time/mix, chorus rate/mix, comp
  ratio). Every prediction displays the model's held-out MAE. The synthetic-to-real
  domain gap is disclosed in the UI.
- **Chorus detection is model-only — three hand-crafted detectors failed.**
  Spectral-centroid wobble, per-bin envelope modulation, and cepstral delay
  tracking all drowned under note-rate structure on synthetic chorus. The forest
  separates it (validated: predicted mix 0.41 when present vs 0.09 absent) using
  two sub-band modulation features jointly with the rest. There is deliberately no
  rule-based chorus card.
- **Rhythm is an adversary to modulation detectors.** Notes played at 4 Hz *are*
  a 4 Hz amplitude modulation, and a riff "echoes" itself one note later. The
  tremolo/delay detectors mask the onset rate and its harmonics. Cost, documented:
  tempo-synced delay is invisible.
- **Reverb vs distortion sustain is genuinely ambiguous.** When the decay estimate
  maxes out on a heavily driven signal, the chain reports "reverb (uncertain)"
  rather than claiming a hall.
- **Closed-loop matching sidesteps the identification problem.** Comparing the
  user's recording to the target is differential measurement — signed feature
  deltas become directional advice. Caveat shipped with results: the target stem
  passed through a separation model and the user's recording didn't.

## Lyrics

- faster-whisper (CPU int8, VAD-filtered) over the separated vocals stem; each
  line gets the chord sounding at its midpoint. Sung-word recognition mishears;
  labeled heuristic. Degrades to nothing on instrumentals or missing deps.

## Conventions

- Every report section carries a confidence label: `verified` (measured),
  `heuristic` (documented rule with known failure modes), `estimated` (tone).
- Tests synthesize all audio — no copyrighted recordings in the repo, no network.
- Heavy deps (torch/demucs, faster-whisper) are optional extras with lazy imports;
  the core pipeline and full test suite run without them.
