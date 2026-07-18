"""Extract tone-relevant features from (ideally isolated) guitar audio.

Plain English guide to what each number means:

- **Crest factor**: gap between the loudest instants and the average level. Naturally
  picked guitar is spiky (high crest); compression and distortion both squash the
  spikes (low crest).
- **Flat-top ratio**: how often the waveform sits pinned near its maximum. Hard
  clipping (distortion/fuzz) literally flattens wave tops, so a high value means
  aggressive clipping somewhere in the chain.
- **Harmonic distortion index**: energy at multiples of the played pitch versus at the
  pitch itself. Overdrive adds harmonics, so dirtier tone ⇒ higher index. Measured
  only on frames where pitch tracking is confident.
- **Band energy / tilt**: how energy splits across lows / mids / presence / treble —
  the EQ "shape" of the tone (mid-scooped metal vs mid-forward blues, dark vs bright).
- **Decay time (T60 estimate)**: how long sound takes to fade ~60 dB after notes stop.
  Longer tails ⇒ more reverb (or a very live room).
- **Envelope modulation**: rhythmic wobble of loudness in the 0.5–12 Hz range —
  tremolo/chorus/phaser leave a periodic fingerprint here.
- **Echo delay**: a repeating bump in the loudness envelope's self-similarity at
  100–1000 ms suggests a delay pedal and gives its approximate time.

All of these are indirect evidence. Downstream mapping treats them as hints, never
proof (label: estimated).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import librosa
import numpy as np
import scipy.signal


@dataclass
class ToneFeatures:
    rms_db: float
    crest_db: float
    flat_top_ratio: float
    harmonic_distortion: float      # 0..~1+, harmonic-to-fundamental energy ratio
    spectral_centroid_hz: float
    band_energy: dict[str, float]   # fraction of energy per band, sums to ~1
    tilt_db_per_octave: float       # + = bright, − = dark
    decay_t60_s: float              # estimated; capped at 6 s
    dynamic_range_db: float         # p95 − p10 of frame RMS
    modulation_hz: float            # 0 if no clear periodic envelope modulation
    modulation_depth: float         # 0..1
    echo_delay_s: float             # 0 if no clear echo
    echo_strength: float            # 0..1 envelope autocorrelation at the echo lag
    # Sub-band spectral modulation (0.3-4 Hz, note rate masked): the raw material
    # for chorus detection. No hand-written rule can call "chorus" from these two
    # numbers alone (validated: single-feature detectors failed on synthetic
    # chorus) — only the learned model reads them, jointly with everything else.
    subband_mod_hz: float = 0.0
    subband_mod_depth: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def features_from_dict(d: dict) -> "ToneFeatures":
    """Rebuild ToneFeatures from a stored report dict, tolerating reports written
    by older versions that lack newer (defaulted) fields."""
    import dataclasses
    known = {f.name for f in dataclasses.fields(ToneFeatures)}
    return ToneFeatures(**{k: v for k, v in d.items() if k in known})


BANDS = {
    "low (80-250 Hz)": (80, 250),
    "mid (250-2000 Hz)": (250, 2000),
    "presence (2-6 kHz)": (2000, 6000),
    "treble (6-10 kHz)": (6000, 10000),
}


def extract_tone_features(y: np.ndarray, sr: int) -> ToneFeatures:
    y = np.asarray(y, dtype=np.float32)
    if len(y) < sr // 4 or float(np.max(np.abs(y))) < 1e-5:
        raise ValueError("audio too short or silent for tone analysis")
    y = y / np.max(np.abs(y))

    hop = 512
    frame_rms = librosa.feature.rms(y=y, hop_length=hop)[0]
    active = frame_rms > 0.05 * np.max(frame_rms)

    rms = float(np.sqrt(np.mean(y**2)))
    rms_db = 20 * np.log10(rms + 1e-9)
    crest_db = 20 * np.log10(1.0 / (rms + 1e-9))  # peak is 1.0 after normalization

    # Fraction of samples pinned within 2% of full scale (hard-clipping fingerprint)
    flat_top_ratio = float(np.mean(np.abs(y) > 0.98))

    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=hop))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    centroid = float(np.mean(
        librosa.feature.spectral_centroid(S=S[:, active[:S.shape[1]]], sr=sr)))

    total = float(np.sum(S**2)) + 1e-12
    band_energy = {}
    for name, (lo, hi) in BANDS.items():
        sel = (freqs >= lo) & (freqs < hi)
        band_energy[name] = round(float(np.sum(S[sel] ** 2)) / total, 4)

    tilt = _spectral_tilt(S, freqs)
    hdist = _harmonic_distortion(y, sr, S, freqs, hop)
    t60 = _decay_time(frame_rms, sr, hop)
    dyn = _dynamic_range(frame_rms, active)

    # Played-note rhythm is itself an amplitude modulation (8th notes at 120 bpm
    # pulse at 4 Hz) and an envelope echo (each note "repeats" one note later).
    # Both detectors must ignore the note rate and its harmonics or every riff
    # reads as tremolo + delay. Tempo-synced delay is therefore invisible to us —
    # documented limitation.
    onsets = librosa.onset.onset_detect(y=y, sr=sr, hop_length=hop, units="time")
    onset_rate = 0.0
    if len(onsets) >= 3:
        onset_rate = 1.0 / float(np.median(np.diff(onsets)))

    mod_hz, mod_depth = _envelope_modulation(frame_rms, sr, hop, onset_rate)
    echo_s, echo_strength = _echo(frame_rms, sr, hop, onset_rate)
    sb_hz, sb_depth = _subband_modulation(S, freqs, sr, hop, onset_rate)

    return ToneFeatures(
        rms_db=round(rms_db, 2), crest_db=round(crest_db, 2),
        flat_top_ratio=round(flat_top_ratio, 5),
        harmonic_distortion=round(hdist, 4),
        spectral_centroid_hz=round(centroid, 1),
        band_energy=band_energy, tilt_db_per_octave=round(tilt, 2),
        decay_t60_s=round(t60, 2), dynamic_range_db=round(dyn, 2),
        modulation_hz=round(mod_hz, 2), modulation_depth=round(mod_depth, 3),
        echo_delay_s=round(echo_s, 3), echo_strength=round(echo_strength, 3),
        subband_mod_hz=round(sb_hz, 2), subband_mod_depth=round(sb_depth, 4),
    )


def _spectral_tilt(S: np.ndarray, freqs: np.ndarray) -> float:
    """Slope of mean log-power vs log2(frequency), in dB/octave, 100 Hz–8 kHz."""
    power = np.mean(S**2, axis=1)
    sel = (freqs >= 100) & (freqs <= 8000) & (power > 0)
    x = np.log2(freqs[sel])
    ydb = 10 * np.log10(power[sel] + 1e-12)
    slope = float(np.polyfit(x, ydb, 1)[0])
    return slope


def _harmonic_distortion(y, sr, S, freqs, hop) -> float:
    """Mean energy(harmonics 2..8) / energy(fundamental) over pitch-confident frames."""
    f0, _, vprob = librosa.pyin(y, fmin=70, fmax=1200, sr=sr, hop_length=hop,
                                fill_na=np.nan)
    n = min(len(f0), S.shape[1])
    ratios = []
    bin_hz = freqs[1] - freqs[0]
    for i in range(n):
        if np.isnan(f0[i]) or vprob[i] < 0.5:
            continue
        fund = f0[i]
        def band_e(f):
            lo, hi = f - 1.5 * bin_hz, f + 1.5 * bin_hz
            sel = (freqs >= lo) & (freqs <= hi)
            return float(np.sum(S[sel, i] ** 2))
        e1 = band_e(fund)
        if e1 <= 0:
            continue
        eh = sum(band_e(k * fund) for k in range(2, 9) if k * fund < sr / 2)
        ratios.append(eh / e1)
    return float(np.median(ratios)) if ratios else 0.0


def _decay_time(frame_rms, sr, hop) -> float:
    """Estimate T60 from the steepest sustained decays in the dB envelope.

    We find stretches where level falls monotonically-ish for ≥150 ms, fit a line to
    each, and take the *shallowest* decay among note tails — reverb sets a floor on
    how fast anything can fade. Capped at 6 s (beyond that it's a pad, not a tail).
    """
    db = 20 * np.log10(frame_rms + 1e-9)
    fps = sr / hop
    win = max(3, int(0.15 * fps))
    slopes = []
    for i in range(0, len(db) - win, win // 2):
        seg = db[i:i + win]
        slope = np.polyfit(np.arange(win) / fps, seg, 1)[0]  # dB per second
        if slope < -3:  # only genuine decays
            slopes.append(-slope)
    if not slopes:
        return 6.0  # nothing ever decays ⇒ wall of sustain
    # 20th percentile of decay rates ≈ the slow reverb floor, robust to outliers
    rate = float(np.percentile(slopes, 20))
    return float(min(60.0 / rate, 6.0))


def _dynamic_range(frame_rms, active) -> float:
    act = frame_rms[active]
    if len(act) < 4:
        return 0.0
    db = 20 * np.log10(act + 1e-9)
    return float(np.percentile(db, 95) - np.percentile(db, 10))


def _subband_modulation(S, freqs, sr, hop, onset_rate: float) -> tuple[float, float]:
    """Slow (0.3-4 Hz) modulation of individual frequency-band envelopes.

    Chorus/flanger sweep comb notches through the spectrum: each frequency bin's
    level wobbles at the effect rate, with phases that differ across bins. We
    average each bin's detrended log-envelope modulation spectrum and pick the
    strongest non-note-rate peak. Kept as raw evidence for the learned model.
    """
    fps = sr / hop
    sel = (freqs >= 500) & (freqs <= 6000)
    L = np.log(S[sel] + 1e-6)
    if L.shape[1] < int(4 * fps):
        return 0.0, 0.0
    k = max(3, int(fps))
    kernel = np.ones(k) / k
    trend = np.apply_along_axis(lambda r: np.convolve(r, kernel, "same"), 1, L)
    f_m, psd = scipy.signal.periodogram(L - trend, fs=fps, axis=1)
    mean_psd = psd.mean(axis=0)
    band = (f_m >= 0.3) & (f_m <= 4.0)
    mask = band & ~np.array([_near_onset_harmonic(f, onset_rate) for f in f_m])
    if not np.any(mask):
        return 0.0, 0.0
    peak = int(np.argmax(mean_psd[mask]))
    depth = float(mean_psd[mask][peak] / (np.sum(mean_psd[band]) + 1e-12))
    return float(f_m[mask][peak]), depth


def _near_onset_harmonic(f: float, onset_rate: float, rel_tol: float = 0.18) -> bool:
    if onset_rate <= 0:
        return False
    k = round(f / onset_rate)
    return k >= 1 and abs(f - k * onset_rate) <= rel_tol * onset_rate


def _envelope_modulation(frame_rms, sr, hop, onset_rate: float) -> tuple[float, float]:
    """Strongest periodic loudness wobble in 0.5–12 Hz, excluding the note rate."""
    fps = sr / hop
    env = frame_rms - np.mean(frame_rms)
    if len(env) < int(4 * fps):
        return 0.0, 0.0
    freqs_m, psd = scipy.signal.periodogram(env, fs=fps)
    sel = (freqs_m >= 0.5) & (freqs_m <= 12)
    sel &= ~np.array([_near_onset_harmonic(f, onset_rate) for f in freqs_m])
    if not np.any(sel):
        return 0.0, 0.0
    peak_idx = np.argmax(psd[sel])
    peak_f = float(freqs_m[sel][peak_idx])
    # depth: peak power relative to total envelope variance
    depth = float(psd[sel][peak_idx] / (np.sum(psd) + 1e-12))
    if depth < 0.05:
        return 0.0, 0.0
    return peak_f, min(depth, 1.0)


def _echo(frame_rms, sr, hop, onset_rate: float) -> tuple[float, float]:
    """Repeating bump in envelope self-similarity at 100–1000 ms, excluding lags
    at multiples of the note period (a riff 'echoes' itself at the note rate)."""
    fps = sr / hop
    env = frame_rms - np.mean(frame_rms)
    if len(env) < int(3 * fps):
        return 0.0, 0.0
    ac = np.correlate(env, env, mode="full")[len(env) - 1:]
    ac = ac / (ac[0] + 1e-12)
    lo, hi = int(0.1 * fps), min(int(1.0 * fps), len(ac) - 1)
    if hi <= lo:
        return 0.0, 0.0
    seg = ac[lo:hi]
    peaks, props = scipy.signal.find_peaks(seg, height=0.25, prominence=0.1)
    def is_note_period_multiple(lag_s: float) -> bool:
        if onset_rate <= 0:
            return False
        cycles = lag_s * onset_rate  # how many note periods fit in this lag
        return cycles >= 0.8 and abs(cycles - round(cycles)) <= 0.18

    keep = [(p, h) for p, h in zip(peaks, props["peak_heights"])
            if not is_note_period_multiple((lo + p) / fps)]
    if not keep:
        return 0.0, 0.0
    best, height = max(keep, key=lambda t: t[1])
    return float((lo + best) / fps), float(height)
