"""Map measured tone features to an effect-chain estimate.

Plain English: this is the "how do I get that sound?" step. It never claims to know
what gear was used — it can't; nothing can, from audio alone. It says "this much
clipping and this EQ shape usually comes from <category>; on your gear, start
around these settings and tune by ear."

Every output is labeled `estimated`. Ranges are starting points, not measurements
of the original rig. Rules are calibrated against the synthetic-effect tests in
tests/test_tone_features.py plus standard guitar-signal reasoning, NOT a labeled
dataset of real pedals — treat accordingly.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .features import ToneFeatures

CONFIDENCE_LABEL = "estimated"


@dataclass
class EffectEstimate:
    effect: str                  # category, e.g. "overdrive", "reverb"
    verdict: str                 # plain-English one-liner
    settings: dict[str, str]     # knob → suggested starting range
    evidence: str                # which measurements drove this call
    strength: float              # 0..1 how present the effect seems
    confidence: str = CONFIDENCE_LABEL


@dataclass
class ToneEstimate:
    summary: str                      # plain-English paragraph
    chain: list[EffectEstimate] = field(default_factory=list)
    amp_eq: dict[str, str] = field(default_factory=dict)
    confidence: str = CONFIDENCE_LABEL

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "chain": [asdict(e) for e in self.chain],
            "amp_eq": self.amp_eq,
            "confidence": self.confidence,
        }


def _drive(f: ToneFeatures) -> EffectEstimate:
    """Gain staging from clipping fingerprint + harmonic content + squash."""
    # 0..1 drive index: flat-top ratio is the strongest clue (clean audio has ~0),
    # then harmonic buildup, then crest collapse (clean pluck ≈ 12–18 dB).
    ft = min(f.flat_top_ratio / 0.10, 1.0)
    hd = min(max(f.harmonic_distortion - 0.8, 0.0) / 1.5, 1.0)
    crush = min(max(14.0 - f.crest_db, 0.0) / 10.0, 1.0)
    index = 0.5 * ft + 0.3 * hd + 0.2 * crush

    evidence = (f"flat-top ratio {f.flat_top_ratio:.3f}, harmonic index "
                f"{f.harmonic_distortion:.2f}, crest {f.crest_db:.1f} dB")
    if index < 0.15:
        return EffectEstimate("clean", "essentially clean — no audible clipping",
                              {"amp gain": "2–4 (clean channel)"},
                              evidence, round(index, 2))
    if index < 0.35:
        return EffectEstimate("edge-of-breakup",
                              "lightly driven — clips only on hard picking",
                              {"amp gain": "4–6, or low-gain OD (drive 9–11 o'clock, "
                               "level high)"}, evidence, round(index, 2))
    if index < 0.6:
        return EffectEstimate("overdrive", "clearly overdriven, still dynamic",
                              {"drive": "12–3 o'clock", "tone": "to taste",
                               "amp gain": "5–7"}, evidence, round(index, 2))
    if index < 0.85:
        return EffectEstimate("distortion", "heavily clipped, compressed feel",
                              {"gain": "2–4 o'clock (distortion pedal or high-gain "
                               "channel)"}, evidence, round(index, 2))
    return EffectEstimate("fuzz/high-gain", "saturated — wave tops flattened hard",
                          {"fuzz/gain": "max-ish; back off guitar volume to clean up"},
                          evidence, round(index, 2))


def _compression(f: ToneFeatures, drive_strength: float) -> EffectEstimate | None:
    """Crest collapse not explained by clipping ⇒ a compressor is likely."""
    squash = max(14.0 - f.crest_db, 0.0) / 10.0
    attributable = squash - 0.7 * drive_strength   # clipping squashes crest too
    if attributable < 0.15:
        return None
    level = "light" if attributable < 0.35 else ("medium" if attributable < 0.6
                                                 else "heavy")
    return EffectEstimate(
        "compressor", f"{level} compression beyond what the drive explains",
        {"ratio": {"light": "2:1–3:1", "medium": "3:1–5:1",
                   "heavy": "5:1 and up"}[level],
         "attack": "medium-slow (let pick attack through)"},
        f"crest {f.crest_db:.1f} dB, dynamic range {f.dynamic_range_db:.1f} dB, "
        f"drive strength {drive_strength:.2f}",
        round(min(attributable, 1.0), 2))


def _reverb(f: ToneFeatures) -> EffectEstimate | None:
    t60 = f.decay_t60_s
    if t60 < 0.5:
        return None
    if t60 < 1.2:
        kind, decay = "room reverb", "small room, decay 0.5–1 s, mix 15–25%"
    elif t60 < 2.5:
        kind, decay = "plate/hall reverb", "decay 1–2.5 s, mix 20–35%"
    else:
        kind, decay = "large hall/ambient reverb", "decay 3 s+, mix 30–50%"
    return EffectEstimate(
        "reverb", f"tails ring for roughly {t60:.1f} s — {kind}",
        {"decay/mix": decay},
        f"estimated T60 {t60:.1f} s from note-tail decay slopes",
        round(min(t60 / 4.0, 1.0), 2))


def _modulation(f: ToneFeatures) -> EffectEstimate | None:
    if f.modulation_depth <= 0 or f.modulation_hz <= 0:
        return None
    hz = f.modulation_hz
    if hz < 1.5:
        kind, note = "slow modulation (phaser/chorus)", "rate at its slowest, depth moderate"
    elif hz < 8:
        kind, note = "tremolo/vibrato-range modulation", "square or sine tremolo"
    else:
        kind, note = "fast tremolo", "fast rate; check it isn't ring-mod territory"
    return EffectEstimate(
        "modulation", f"loudness wobbles at ~{hz:.1f} Hz — {kind}",
        {"rate": f"~{hz:.1f} Hz", "depth": f"~{min(f.modulation_depth * 2, 1.0):.0%}",
         "note": note},
        f"envelope modulation peak {hz:.1f} Hz, depth {f.modulation_depth:.2f} "
        "(note-rate harmonics excluded)",
        round(min(f.modulation_depth * 2, 1.0), 2))


def _delay(f: ToneFeatures) -> EffectEstimate | None:
    if f.echo_strength <= 0 or f.echo_delay_s <= 0:
        return None
    ms = f.echo_delay_s * 1000
    return EffectEstimate(
        "delay", f"repeats roughly every {ms:.0f} ms",
        {"time": f"~{ms:.0f} ms", "feedback": "1–3 repeats",
         "mix": f"~{min(f.echo_strength, 0.5):.0%}"},
        f"envelope self-similarity peak at {f.echo_delay_s:.2f} s "
        f"(strength {f.echo_strength:.2f}; tempo-synced delay can't be told apart "
        "from the riff repeating)",
        round(f.echo_strength, 2))


def _amp_eq(f: ToneFeatures) -> tuple[dict[str, str], str]:
    be = f.band_energy
    low = be.get("low (80-250 Hz)", 0)
    mid = be.get("mid (250-2000 Hz)", 0)
    pres = be.get("presence (2-6 kHz)", 0)
    body = low + mid + pres + 1e-9

    eq: dict[str, str] = {}
    desc: list[str] = []
    mid_share = mid / body
    if mid_share < 0.35:
        desc.append("mid-scooped")
        eq["mids"] = "3–4 (scooped)"
    elif mid_share > 0.65:
        desc.append("mid-forward")
        eq["mids"] = "7–8"
    else:
        eq["mids"] = "5–6"
    if f.tilt_db_per_octave > -1.5:
        desc.append("bright")
        eq["treble"] = "6–8"
        eq["bass"] = "3–5"
    elif f.tilt_db_per_octave < -6:
        desc.append("dark/warm")
        eq["treble"] = "3–4"
        eq["bass"] = "6–7"
    else:
        eq["treble"] = "5–6"
        eq["bass"] = "5–6"
    character = ", ".join(desc) if desc else "balanced"
    return eq, character


def estimate_tone(f: ToneFeatures) -> ToneEstimate:
    drive = _drive(f)
    chain: list[EffectEstimate] = [drive]
    for est in (_compression(f, drive.strength), _modulation(f), _delay(f),
                _reverb(f)):
        if est is not None:
            chain.append(est)

    eq, character = _amp_eq(f)

    ambience = next((e for e in chain if e.effect == "reverb"), None)
    summary = (
        f"ESTIMATE (not a gear identification): {drive.effect} tone with a "
        f"{character} EQ character"
        + (f", {ambience.verdict.split('—')[-1].strip()}" if ambience else ", fairly dry")
        + ". Start with the suggested settings below and tune by ear — the same "
          "sound can come from many different rigs."
    )
    return ToneEstimate(summary=summary, chain=chain, amp_eq=eq)
