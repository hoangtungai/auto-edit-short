"""Step 3a: Robust Video Matting -> person.webm (VP9 + alpha) and head_track.json.

head_track.json: per-frame top of head (y of first row with alpha > 0.5) and head centre x,
used to place head text behind the head and by QA to check caption / face overlap.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

import numpy as np

from .common import FPS, H, ROOT, W, save

MODEL = ROOT / "models" / "rvm_mobilenetv3_fp32.torchscript"


def _device():
    import torch

    if torch.backends.mps.is_available():
        try:
            m = torch.jit.load(str(MODEL), map_location="mps").eval()
            with torch.no_grad():
                m(torch.zeros(1, 3, 256, 144, device="mps"), None, None, None, None, 0.25)
            return "mps", m
        except Exception as e:  # MPS can fail on some ops; CPU is fine for mobilenetv3
            print("MPS unavailable for RVM, using CPU:", str(e)[:120])
    return "cpu", torch.jit.load(str(MODEL), map_location="cpu").eval()


def matte(src: Path, out_webm: Path, track_json: Path, downsample: float = 0.25) -> dict:
    import torch

    dev, model = _device()
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(src), "-f", "rawvideo", "-pix_fmt", "rgb24",
                            "-s", f"{W}x{H}", "-"], stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}",
                            "-r", str(FPS), "-i", "-", "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
                            "-b:v", "0", "-crf", "28", "-g", str(FPS), "-deadline", "realtime", "-cpu-used", "8",
                            "-row-mt", "1", "-auto-alt-ref", "0", str(out_webm)], stdin=subprocess.PIPE)
    rec = [None] * 4
    track, n, t0 = [], 0, time.time()
    fsize = W * H * 3
    with torch.no_grad():
        while True:
            buf = dec.stdout.read(fsize)
            if len(buf) < fsize:
                break
            rgb = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
            x = torch.from_numpy(rgb.copy()).to(dev).permute(2, 0, 1).unsqueeze(0).float().div_(255)
            fgr, pha, *rec = model(x, *rec, downsample)
            pha = pha.clamp(0, 1)
            out = torch.cat([fgr.clamp(0, 1), pha], 1)[0].permute(1, 2, 0).mul(255).byte().cpu().numpy()
            enc.stdin.write(out.tobytes())
            a = out[:, :, 3]
            rows = np.where((a > 128).sum(1) > 12)[0]
            top = int(rows[0]) if len(rows) else H
            band = a[top:top + 160] > 128 if len(rows) else None
            cx = int(np.where(band.any(0))[0].mean()) if band is not None and band.any() else W // 2
            track.append({"f": n, "head_top": top, "head_cx": cx})
            n += 1
            if n % 150 == 0:
                print(f"  matte {n} frames ({n / (time.time() - t0):.1f} fps)", flush=True)
    enc.stdin.close()
    enc.wait()
    dec.wait()
    tops = [t["head_top"] for t in track]
    summary = {"frames": n, "fps": FPS, "device": dev, "head_top_median": int(np.median(tops)),
               "head_top_min": int(min(tops)), "head_cx_median": int(np.median([t["head_cx"] for t in track])),
               "track": track}
    save(track_json, summary)
    return summary
