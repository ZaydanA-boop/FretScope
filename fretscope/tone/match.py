"""Closed-loop tone matching: compare YOUR recording against the song's tone.

Plain English: nothing can name the gear on a record, but comparing two
recordings is a different, much easier problem — measure the same features on
both and report the differences as adjustments. "You're 4 dB brighter, half the
drive, and dry where the record has a half-second tail."

The advice is directional, not absolute (label: estimated). Big known caveat:
the target stem came out of a separation model and your recording is a direct
signal, so some difference is separation artifact, not your tone. Differences
below each threshold are reported as "close" rather than nitpicked.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .features import ToneFeatures


@dataclass
class MatchAdvice:
    aspect: str        # e.g. "drive", "brightness"
    status: str        # "close" | "adjust"
    delta: float       # signed measured difference (attempt − target)
    unit: str
    text: str          # plain-English instruction

    def to_dict(self) -> dict:
        return asdict(self)


def _drive_index(f: ToneFeatures) -> float:
    """Same composite the mapper uses: 0 (clean) .. 1 (fuzz)."""
    ft = min(f.flat_top_ratio / 0.10, 1.0)
    hd = min(max(f.harmonic_distortion - 0.8, 0.0) / 1.5, 1.0)
    crush = min(max(14.0 - f.crest_db, 0.0) / 10.0, 1.0)
    return 0.5 * ft + 0.3 * hd + 0.2 * crush


def compare_tones(target: ToneFeatures, attempt: ToneFeatures) -> list[MatchAdvice]:
    advice: list[MatchAdvice] = []

    # Drive
    d = _drive_index(attempt) - _drive_index(target)
    if abs(d) < 0.12:
        advice.append(MatchAdvice("drive", "close", round(d, 2), "index",
                                  "Gain level is in the zone."))
    elif d > 0:
        advice.append(MatchAdvice("drive", "adjust", round(d, 2), "index",
                                  "You have noticeably more gain than the record. "
                                  "Back the drive off" +
                                  (" a lot." if d > 0.35 else " a little.")))
    else:
        advice.append(MatchAdvice("drive", "adjust", round(d, 2), "index",
                                  "The record is dirtier than you. Add drive" +
                                  (" substantially." if d < -0.35 else " slightly.")))

    # Brightness / EQ tilt
    dt = attempt.tilt_db_per_octave - target.tilt_db_per_octave
    if abs(dt) < 1.5:
        advice.append(MatchAdvice("brightness", "close", round(dt, 1), "dB/octave",
                                  "Overall brightness matches."))
    else:
        direction = "darker: roll treble down or tone knob back" if dt > 0 else \
                    "brighter: bring treble/presence up"
        advice.append(MatchAdvice("brightness", "adjust", round(dt, 1), "dB/octave",
                                  f"Your tone is {'brighter' if dt > 0 else 'darker'} "
                                  f"than the record by ~{abs(dt):.1f} dB/octave. "
                                  f"Go {direction}."))

    # Mid balance
    def mid_share(f: ToneFeatures) -> float:
        be = f.band_energy
        low = be.get("low (80-250 Hz)", 0)
        mid = be.get("mid (250-2000 Hz)", 0)
        pres = be.get("presence (2-6 kHz)", 0)
        return mid / (low + mid + pres + 1e-9)

    dm = mid_share(attempt) - mid_share(target)
    if abs(dm) < 0.1:
        advice.append(MatchAdvice("mids", "close", round(dm, 2), "share",
                                  "Mid balance matches."))
    else:
        advice.append(MatchAdvice("mids", "adjust", round(dm, 2), "share",
                                  "Cut mids a touch." if dm > 0 else
                                  "Push mids up; the record is more mid-forward."))

    # Reverb tail
    dr = attempt.decay_t60_s - target.decay_t60_s
    if abs(dr) < 0.4:
        advice.append(MatchAdvice("reverb", "close", round(dr, 1), "s",
                                  "Ambience/tail length is close."))
    elif dr > 0:
        advice.append(MatchAdvice("reverb", "adjust", round(dr, 1), "s",
                                  f"Your tail rings ~{dr:.1f} s longer. Shorten the "
                                  "reverb decay or lower its mix."))
    else:
        advice.append(MatchAdvice("reverb", "adjust", round(dr, 1), "s",
                                  f"The record's tail is ~{-dr:.1f} s longer than "
                                  "yours. Add reverb decay/mix."))

    # Delay
    t_echo, a_echo = target.echo_strength > 0, attempt.echo_strength > 0
    if t_echo and not a_echo:
        advice.append(MatchAdvice("delay", "adjust",
                                  round(target.echo_delay_s, 2), "s",
                                  f"The record repeats around "
                                  f"{target.echo_delay_s * 1000:.0f} ms; add a delay "
                                  "at that time with 1-3 repeats."))
    elif a_echo and not t_echo:
        advice.append(MatchAdvice("delay", "adjust",
                                  round(-attempt.echo_delay_s, 2), "s",
                                  "You have an audible delay the record doesn't. "
                                  "Turn it off or bury the mix."))
    elif t_echo and a_echo:
        dd = attempt.echo_delay_s - target.echo_delay_s
        if abs(dd) < 0.06:
            advice.append(MatchAdvice("delay", "close", round(dd, 2), "s",
                                      "Delay time matches."))
        else:
            advice.append(MatchAdvice("delay", "adjust", round(dd, 2), "s",
                                      f"Delay time is off by ~{abs(dd) * 1000:.0f} ms "
                                      f"({'slow it down' if dd < 0 else 'speed it up'} "
                                      "to match)."))
    else:
        advice.append(MatchAdvice("delay", "close", 0.0, "s",
                                  "Neither has an audible delay."))

    # Compression / dynamics
    dc = attempt.crest_db - target.crest_db
    if abs(dc) < 3.0:
        advice.append(MatchAdvice("dynamics", "close", round(dc, 1), "dB",
                                  "Dynamics are comparable."))
    else:
        advice.append(MatchAdvice("dynamics", "adjust", round(dc, 1), "dB",
                                  "Your playing is more dynamic than the record; "
                                  "add light compression."
                                  if dc > 0 else
                                  "You're more squashed than the record; ease off "
                                  "compression or gain."))

    return advice


CAVEAT = (
    "Directional estimates from comparing audio features. The song's stem passed "
    "through a separation model and your recording didn't, so small differences "
    "(especially reverb and brightness) partly reflect separation artifacts."
)
