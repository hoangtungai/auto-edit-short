"""Step 4b: self-check the final render.

- format: 1080x1920, H.264 + AAC, duration matches the plan
- loudness: integrated -14 ± 1 LUFS
- clipped words at cut points: words in the re-transcription match the kept words; no tiny words at joins
- caption occlusion: caption box vs face box (from the matte), vs MG card in split, inside 80% title-safe
- frames at every cut point / scene boundary / scene middle -> qa/*.jpg contact sheets for a visual pass
"""
from __future__ import annotations

import difflib
import re
import subprocess
from pathlib import Path

from .common import FPS, H, ROOT, W, load, norm, run, save

FACE_HALF_W = 230
FACE_H = 560


def probe(path: Path) -> dict:
    out = run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height:format=duration",
               "-of", "json", str(path)]).stdout
    import json
    return json.loads(out)


def integrated_lufs(path: Path) -> float:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-vn", "-af", "ebur128", "-f", "null", "-"],
                       capture_output=True, text=True)
    vals = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)
    return float(vals[-1])


def sheet(video: Path, times: list[float], dst: Path, cols: int = 5) -> None:
    tmp = dst.parent / "_frames"
    tmp.mkdir(exist_ok=True)
    for f in tmp.glob("*.jpg"):
        f.unlink()
    for k, t in enumerate(times):
        run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0, t):.3f}", "-i", str(video), "-frames:v", "1",
             "-vf", f"scale=270:480,drawtext=text='{t:.2f}s':x=8:y=8:fontsize=22:fontcolor=yellow:box=1:boxcolor=black@0.6",
             str(tmp / f"{k:03d}.jpg")])
    rows = (len(times) + cols - 1) // cols
    run(["ffmpeg", "-v", "error", "-y", "-framerate", "1", "-i", str(tmp / "%03d.jpg"), "-vf",
         f"tile={cols}x{rows}:padding=4:color=black", "-frames:v", "1", str(dst)])


def qa(name: str) -> dict:
    wd = ROOT / "work" / name
    out = ROOT / "output" / f"{name}_final.mp4"
    qd = wd / "qa"
    qd.mkdir(exist_ok=True)
    plan, lay = load(wd / "edit_plan.json"), load(wd / "layout.json")
    track = load(wd / "head_track.json")["track"]
    errors, warnings, info = [], [], {}

    # ---- format
    p = probe(out)
    v = next(s for s in p["streams"] if s["codec_type"] == "video")
    a = next((s for s in p["streams"] if s["codec_type"] == "audio"), None)
    dur = float(p["format"]["duration"])
    info["format"] = {"video": v["codec_name"], "size": f"{v['width']}x{v['height']}",
                      "audio": a and a["codec_name"], "duration": round(dur, 3)}
    if (v["width"], v["height"]) != (W, H) or v["codec_name"] != "h264":
        errors.append(f"video must be h264 {W}x{H}, got {v['codec_name']} {v['width']}x{v['height']}")
    if not a or a["codec_name"] != "aac":
        errors.append("audio must be AAC")
    if abs(dur - plan["duration"]) > 0.15:
        errors.append(f"duration {dur:.2f}s differs from plan {plan['duration']}s")

    # ---- loudness
    lufs = integrated_lufs(out)
    info["lufs"] = lufs
    if abs(lufs + 14) > 1.0:
        errors.append(f"loudness {lufs} LUFS (target -14 ± 1)")

    # ---- clipped words at cut points
    cut_points = [c["out_end"] for c in load(wd / "cut_points.json")][:-1]
    src_tr, cut_tr = load(wd / "transcript.json"), load(wd / "transcript.cut.json")
    cl = load(wd / "cut_list.json")
    from .cutlist import removed_words
    gone = removed_words(src_tr, cl["cuts"])
    kept = [norm(w["text"]) for w in src_tr["words"] if w["i"] not in gone and not w["filler"]]
    got = [norm(w["text"]) for w in cut_tr["words"] if not w["filler"]]
    sm = difflib.SequenceMatcher(a=kept, b=got, autojunk=False)
    info["kept_vs_recut_similarity"] = round(sm.ratio(), 3)
    lost = [" ".join(kept[i1:i2]) for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag in ("delete", "replace")]
    if sm.ratio() < 0.9:
        errors.append(f"re-transcription differs from kept words ({sm.ratio():.0%}); lost/changed: {lost[:6]}")
    elif lost:
        warnings.append(f"minor transcript differences after cut: {lost[:6]}")
    for cp in cut_points:
        near = [w for w in cut_tr["words"] if abs(w["start"] - cp) < 0.4 or abs(w["end"] - cp) < 0.4]
        short = [w["text"] for w in near if w["end"] - w["start"] < 0.07]
        if short:
            warnings.append(f"very short word(s) near cut {cp:.2f}s: {short} (possible clipped syllable)")
    info["cut_points"] = cut_points

    # ---- caption occlusion / safe area
    shift = lay["split_shift"]
    occl = []
    for c in lay["captions"]:
        f0, f1 = int(c["start"] * FPS), max(int(c["start"] * FPS) + 1, int(c["end"] * FPS))
        fr = track[f0:f1] or track[-1:]
        dy = shift if c["layout"] == "split" else 0
        face_top = min(x["head_top"] for x in fr) + dy + 40  # skip the cap brim
        face_bottom = face_top + FACE_H
        cx = sum(x["head_cx"] for x in fr) / len(fr)
        x0, x1 = W / 2 - c["width"] / 2, W / 2 + c["width"] / 2
        if x0 < W * 0.1 - 4 or x1 > W * 0.9 + 4 or c["top"] < H * 0.1 or c["bottom"] > H * 0.9:
            occl.append(f"{c['id']} '{c['text']}' outside 80% title-safe")
        if c["layout"] != "fullscreen":
            overlap_x = min(x1, cx + FACE_HALF_W) - max(x0, cx - FACE_HALF_W)
            overlap_y = min(c["bottom"], face_bottom) - max(c["top"], face_top)
            if overlap_x > 0 and overlap_y > 0:
                occl.append(f"{c['id']} '{c['text']}' at {c['start']}s overlaps the face ({overlap_y:.0f}px)")
        if c["layout"] == "split":
            mid = c["start"] + min(0.25, (c["end"] - c["start"]) / 2)  # same rule compose uses
            sc = next(s for s in lay["scenes"] if s["t"] <= mid < s["end"])
            area = sc.get("mg_area")
            if area and c["top"] < area[1]:
                occl.append(f"{c['id']} '{c['text']}' overlaps the MG card")
    if occl:
        errors += occl
    info["captions_checked"] = len(lay["captions"])

    # ---- head text sits behind the head (partly covered, not eaten)
    for h in lay["head_texts"]:
        cover_px = h["baseline"] - h["head_top"]
        if cover_px < 0:
            warnings.append(f"head text {h['id']} floats above the head (no overlap)")
        elif cover_px > 0.65 * h["size"]:
            warnings.append(f"head text {h['id']} may be mostly hidden by the head")

    # ---- contact sheets
    scenes = lay["scenes"]
    bounds = sorted({round(s["t"], 2) for s in scenes[1:]})
    seam_times = [t + d for t in bounds for d in (-0.2, 0.05, 0.3)]
    sheet(out, seam_times, qd / "transitions.jpg", cols=6)
    mids = [round((s["t"] + s["end"]) / 2, 2) for s in scenes] + [h["t"] + 0.8 for h in lay["head_texts"]]
    sheet(out, sorted(mids), qd / "scenes.jpg", cols=5)
    if cut_points:
        sheet(out, [t + d for t in cut_points for d in (-0.2, 0.0, 0.2)], qd / "cuts.jpg", cols=6)
    report = {"ok": not errors, "errors": errors, "warnings": warnings, "info": info,
              "sheets": [str(p) for p in sorted(qd.glob("*.jpg"))]}
    save(qd / "qa_report.json", report)
    return report
