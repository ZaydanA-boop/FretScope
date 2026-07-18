"""Audio input: ffmpeg discovery, YouTube download, decoding to analysis-ready arrays.

Plain English: everything downstream wants the same thing — a single-channel list of
audio samples at a known rate. This module turns whatever comes in (a YouTube link, an
mp3, an m4a) into that, using ffmpeg as the universal decoder.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from . import ANALYSIS_SR


class AudioIOError(RuntimeError):
    pass


def find_ffmpeg() -> str | None:
    """Locate an ffmpeg executable.

    Search order: FRETSCOPE_FFMPEG env var, PATH, the WinGet links folder (winget
    installs update PATH in the registry but already-running shells don't see it).
    """
    env = os.environ.get("FRETSCOPE_FFMPEG")
    if env and Path(env).exists():
        return env
    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path
    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        winget = Path(localappdata) / "Microsoft" / "WinGet"
        link = winget / "Links" / "ffmpeg.exe"
        if link.exists():
            return str(link)
        # winget doesn't always create the Links shim; fall back to the package dir
        candidates = sorted((winget / "Packages").glob("Gyan.FFmpeg*/**/bin/ffmpeg.exe"))
        if candidates:
            return str(candidates[-1])
    return None


def ensure_ffmpeg_on_path() -> None:
    """Prepend ffmpeg's folder to this process's PATH.

    Libraries that shell out to `ffmpeg`/`ffprobe` by bare name (demucs, yt-dlp
    post-processors) need them on PATH; a fresh winget install only updates the
    registry PATH, not already-running processes.
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return
    bin_dir = str(Path(ffmpeg).parent)
    if bin_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")


def require_ffmpeg() -> str:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise AudioIOError(
            "ffmpeg not found. Install it (e.g. `winget install Gyan.FFmpeg`) or set "
            "FRETSCOPE_FFMPEG to the full path of ffmpeg.exe."
        )
    return ffmpeg


def to_wav(src: Path | str, dst: Path | str | None = None, sr: int = ANALYSIS_SR,
           mono: bool = True) -> Path:
    """Decode any audio file ffmpeg understands into a PCM WAV at the given rate."""
    src = Path(src)
    if not src.exists():
        raise AudioIOError(f"input file does not exist: {src}")
    if dst is None:
        dst = Path(tempfile.mkdtemp(prefix="fretscope_")) / (src.stem + ".wav")
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [require_ffmpeg(), "-y", "-i", str(src), "-vn", "-ar", str(sr)]
    if mono:
        cmd += ["-ac", "1"]
    cmd += ["-f", "wav", str(dst)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AudioIOError(f"ffmpeg failed on {src.name}: {proc.stderr[-800:]}")
    return dst


def load_audio(path: Path | str, sr: int = ANALYSIS_SR) -> tuple[np.ndarray, int]:
    """Load audio as mono float32 at `sr`. Non-WAV/FLAC inputs go through ffmpeg."""
    path = Path(path)
    if path.suffix.lower() not in {".wav", ".flac"}:
        path = to_wav(path, sr=sr)
        data, file_sr = sf.read(path, dtype="float32", always_2d=True)
    else:
        data, file_sr = sf.read(path, dtype="float32", always_2d=True)
        if file_sr != sr:
            path = to_wav(path, sr=sr)
            data, file_sr = sf.read(path, dtype="float32", always_2d=True)
    y = data.mean(axis=1)
    return np.ascontiguousarray(y, dtype=np.float32), file_sr


def save_wav(path: Path | str, y: np.ndarray, sr: int = ANALYSIS_SR) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, np.asarray(y, dtype=np.float32), sr)
    return path


def trim_wav(src: Path | str, dst: Path | str, seconds: float) -> Path:
    """Copy the first `seconds` of a WAV via ffmpeg (stream copy, fast)."""
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [require_ffmpeg(), "-y", "-i", str(src), "-t", str(seconds),
           "-c", "copy", str(dst)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AudioIOError(f"ffmpeg trim failed: {proc.stderr[-500:]}")
    return dst


def wav_duration(path: Path | str) -> float:
    return float(sf.info(str(path)).duration)


def is_youtube_url(text: str) -> bool:
    text = text.strip().lower()
    return text.startswith(("http://", "https://")) and (
        "youtube.com" in text or "youtu.be" in text
    )


MAX_YOUTUBE_MINUTES = 20


def download_youtube(url: str, out_dir: Path | str,
                     progress_hook=None) -> tuple[Path, dict]:
    """Download the audio track of a YouTube video.

    Returns (path to downloaded audio file, info dict with title/uploader/duration).
    Refuses videos longer than MAX_YOUTUBE_MINUTES — those are podcasts/streams,
    not songs, and would grind the CPU pipeline for nothing.
    Conversion to WAV happens later in load_audio, so no ffmpeg post-processing here.
    """
    import yt_dlp  # local import: not needed for tests / offline use

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(out_dir / "source.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        opts["ffmpeg_location"] = str(Path(ffmpeg).parent)
    if progress_hook:
        opts["progress_hooks"] = [progress_hook]
    with yt_dlp.YoutubeDL(opts) as ydl:
        probe = ydl.extract_info(url, download=False)
        duration = probe.get("duration") or 0
        if duration > MAX_YOUTUBE_MINUTES * 60:
            raise AudioIOError(
                f"video is {duration / 60:.0f} minutes long; FretScope caps input "
                f"at {MAX_YOUTUBE_MINUTES} minutes (paste a single song, not a "
                "stream/compilation)")
        info = ydl.extract_info(url, download=True)
    files = sorted(out_dir.glob("source.*"))
    if not files:
        raise AudioIOError(f"yt-dlp reported success but no file found in {out_dir}")
    meta = {
        "title": info.get("title"),
        "uploader": info.get("uploader"),
        "duration": info.get("duration"),
        "webpage_url": info.get("webpage_url", url),
    }
    return files[0], meta
