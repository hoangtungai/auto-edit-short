"""Step 4a: HyperFrames render -> loudnorm (-14 LUFS, 2 pass) -> mux H.264 + AAC -> output/<name>_final.mp4."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from .common import OUTPUT, ROOT, run


def _npx_env() -> dict:
    env = dict(os.environ)
    env.setdefault("npm_config_cache", str(ROOT / ".npm-cache"))  # the user's ~/.npm is root-owned
    return env


def hf(*args: str, timeout: int | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["npx", "hyperframes", *args], cwd=ROOT, env=_npx_env(), capture_output=True, text=True,
                          timeout=timeout)


def loudnorm(src: Path, dst: Path, target: float = -14.0) -> dict:
    p1 = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(src), "-vn", "-af",
                         f"loudnorm=I={target}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                        capture_output=True, text=True)
    m = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p1.stderr, re.S).group(0))
    af = (f"loudnorm=I={target}:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vn", "-af", af, "-ar", "48000", "-c:a", "aac", "-b:a", "192k",
         str(dst)])
    return m


def render(name: str, quality: str = "looks", workers: str = "3") -> Path:
    wd = ROOT / "work" / name
    raw = wd / "render.mp4"
    r = hf("render", str(wd / "hf"), "-o", str(raw), "--quality", quality, "--workers", workers, "--fps", "30",
           "--keyframe-interval", "1", "--quiet")
    if r.returncode != 0 or not raw.exists():
        raise RuntimeError(f"hyperframes render failed:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
    voice = wd / "voice_norm.m4a"
    m = loudnorm(wd / "cut.mp4", voice)
    OUTPUT.mkdir(exist_ok=True)
    out = OUTPUT / f"{name}_final.mp4"
    vinfo = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name,pix_fmt,width,height",
                 "-of", "json", str(raw)]).stdout
    v = json.loads(vinfo)["streams"][0]
    copy_ok = v["codec_name"] == "h264" and v["pix_fmt"] == "yuv420p" and (v["width"], v["height"]) == (1080, 1920)
    vcodec = ["-c:v", "copy"] if copy_ok else ["-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
                                               "-vf", "scale=1080:1920"]
    run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-i", str(voice), "-map", "0:v:0", "-map", "1:a:0", *vcodec,
         "-c:a", "copy", "-shortest", "-movflags", "+faststart", str(out)])
    print(f"✓ render {raw.name} ({'copied' if copy_ok else 're-encoded'} video), loudnorm input {m['input_i']} LUFS -> {out}")
    return out
