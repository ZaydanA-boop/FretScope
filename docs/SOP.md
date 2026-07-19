# SOP — Working agreement for this repo

This is the contract for how work gets done here, human or AI.

## 1. Plain English first

Any technical concept gets explained in plain English *before* the technical detail.
Example: "Reverb makes a note keep ringing after it's played, like singing in a stairwell.
We estimate it by measuring how long sound takes to fade after note endings (decay-tail
regression on the energy envelope)." Reports, docs, commit messages, and dashboard copy all
follow this rule.

## 2. Session start ritual

Read the decision log (`docs/DECISIONS.md`) before touching code. It holds the key decisions, their reasons, and known limitations.
Update it in the same commit as any change that makes it stale.

## 3. Blockers are flagged, not buried

If something can't be done properly (library won't install, method doesn't actually work,
accuracy is bad), say so **before** working around it. Workarounds ship only with:
- a note in `docs/DECISIONS.md` under the relevant section, and
- a visible flag in user-facing output if results are affected.
Never quietly ship something that looks confident but isn't backed by the method.

## 4. Commit conventions

- One commit per completed phase or coherent feature. No giant end-of-project commits.
- Message format: short imperative summary line, blank line, then body explaining *why* and
  any limitation introduced. Reference the phase, e.g. `Phase 3: transcription`.
- Code and the doc updates it requires (DECISIONS.md, SOP) travel in the same commit.
- Never commit downloaded audio, stems, or model weights (`.gitignore` covers this).

## 5. Confidence labeling

Every user-facing result section carries exactly one label:

| Label | Meaning | Examples |
|---|---|---|
| `verified` | Directly measured from the audio; would reproduce | duration, sample rate, RMS level, detected onset times |
| `heuristic` | Derived by a documented rule with known failure modes | fret positions, lead-vs-rhythm classification, chord names |
| `estimated` | Educated guess from indirect evidence; treat as a starting point | everything in tone/effects: drive amount, reverb size, EQ settings, suggested pedal parameters |

Rules:
- Tone/effects output is **always** `estimated`. It is never phrased as "detected X pedal"
  or "identified Y amp" — only "sounds like <category>; try <range>".
- Tab output is **always** `heuristic` — one playable interpretation, not the tab.
- When separation ran on the full mix (no Demucs), downstream labels are downgraded and the
  report states it.

## 6. Testing

`pytest` must pass with only core deps (no torch). Tests synthesize audio (sine waves,
plucked-string models, chords) rather than shipping copyrighted recordings, and never touch
the network.
