"""Shared helpers: paths, JSON IO, ffmpeg wrappers, text normalisation."""
from __future__ import annotations

import json
import re
import subprocess
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
OUTPUT = ROOT / "output"
CONFIG = ROOT / "config"
FPS = 30
W, H = 1080, 1920


def workdir(name: str) -> Path:
    d = WORK / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def name_of(arg: str) -> str:
    """Accept either a name ('short12') or a path ('input/short12.mp4')."""
    return Path(arg).stem


def load(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path: Path, data) -> Path:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return Path(path)


def run(cmd: list[str], quiet: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(map(str, cmd))}\n{r.stderr[-3000:]}")
    if not quiet:
        print(r.stdout)
    return r


def ffprobe_duration(path: Path) -> float:
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    return float(r.stdout.strip())


def extract_audio(src: Path, dst: Path) -> Path:
    run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", str(dst)])
    return dst


def detect_silences(wav: Path, noise_db: float = -35, min_dur: float = 0.2) -> list[list[float]]:
    """Real pauses from the waveform (Whisper word times smear across pauses)."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(wav), "-af",
                        f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-"],
                       capture_output=True, text=True)
    out, start = [], None
    for line in r.stderr.splitlines():
        m = re.search(r"silence_start: ([\d.]+)", line)
        if m:
            start = float(m.group(1))
        m = re.search(r"silence_end: ([\d.]+)", line)
        if m and start is not None:
            out.append([round(start, 3), round(float(m.group(1)), 3)])
            start = None
    return out


_PUNCT =re.compile(r"[^\w\s%]", re.UNICODE)


def norm(text: str) -> str:
    """Lowercase, NFC, strip punctuation; keeps Vietnamese diacritics."""
    t = unicodedata.normalize("NFC", text).lower()
    t = _PUNCT.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def snap(t: float, fps: int = FPS) -> float:
    return round(round(t * fps) / fps, 4)
