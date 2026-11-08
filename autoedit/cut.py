"""Step 1c: cut the source by cut_list.json (approved only) -> cut.mp4 (1080x1920, 30 fps, GOP 1 s)."""
from __future__ import annotations

from pathlib import Path

from .common import FPS, H, W, run
from .cutlist import compute_keep


def cut_video(src: Path, transcript: dict, cut_list: dict, dst: Path) -> list[dict]:
    if not cut_list.get("approved"):
        raise SystemExit("cut_list.json chưa được duyệt: đặt \"approved\": true rồi chạy lại.")
    keep = compute_keep(transcript, cut_list["cuts"], cut_list.get("pad", 0.15))
    fade = cut_list.get("afade_ms", 30) / 1000
    parts, labels = [], []
    for n, k in enumerate(keep):
        d = k["end"] - k["start"]
        parts.append(
            f"[0:v]trim=start={k['start']}:end={k['end']},setpts=PTS-STARTPTS,"
            f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS}[v{n}];"
            f"[0:a]atrim=start={k['start']}:end={k['end']},asetpts=PTS-STARTPTS,"
            f"afade=t=in:st=0:d={fade},afade=t=out:st={max(0, d - fade):.4f}:d={fade}[a{n}]"
        )
        labels.append(f"[v{n}][a{n}]")
    graph = ";".join(parts) + ";" + "".join(labels) + f"concat=n={len(keep)}:v=1:a=1[v][a]"
    script = dst.with_suffix(".filter.txt")
    script.write_text(graph)
    run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-filter_complex_script", str(script),
         "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "16",
         "-g", str(FPS), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
         "-movflags", "+faststart", str(dst)])
    # map of new-time cut points (for QA)
    t, points = 0.0, []
    for k in keep:
        t += k["end"] - k["start"]
        points.append(round(t, 3))
    return [{"src_start": k["start"], "src_end": k["end"], "out_end": p} for k, p in zip(keep, points)]
