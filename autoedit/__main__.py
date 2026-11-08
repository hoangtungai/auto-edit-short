"""CLI entry: python -m autoedit <command> <name|path>"""
from __future__ import annotations

import argparse
from pathlib import Path

from .common import ROOT, load, name_of, save, workdir


def cmd_transcribe(a):
    from .transcribe import transcribe

    src = Path(a.target)
    if not src.exists():
        src = ROOT / "input" / f"{name_of(a.target)}.mp4"
    wd = workdir(name_of(a.target))
    try:
        rel = str(src.resolve().relative_to(ROOT))
    except ValueError:
        rel = str(src)
    save(wd / "meta.json", {"name": name_of(a.target), "source": rel})
    data = transcribe(src, wd / "transcript.json", a.engine)
    print(f"✓ {len(data['words'])} từ, {len(data['segments'])} câu -> {wd / 'transcript.json'}")
    for s in data["segments"]:
        print(f"  [{s['start']:6.2f}-{s['end']:6.2f}] {s['text']}")


def cmd_cutlist(a):
    from .cutlist import build_cut_list

    wd = workdir(name_of(a.target))
    cl = build_cut_list(load(wd / "transcript.json"))
    save(wd / "cut_list.json", cl)
    print(f"✓ {wd / 'cut_list.json'}  ({cl['stats']})")
    for c in cl["cuts"]:
        extra = f"  ~{c['similarity']:.0%} giống '{c['kept_text'][:50]}'" if c["reason"] == "retake" else ""
        print(f"  {c['id']:>4} {c['reason']:8} {c['start']:6.2f}-{c['end']:6.2f}  {c['text'][:70]}{extra}")
    print("→ Duyệt file, sửa 'enabled' nếu cần, rồi đặt \"approved\": true và chạy: python -m autoedit cut", a.target)


def cmd_cut(a):
    from .cut import cut_video
    from .transcribe import transcribe

    wd = workdir(name_of(a.target))
    meta = load(wd / "meta.json")
    cl = load(wd / "cut_list.json")
    segs = cut_video(ROOT / meta["source"], load(wd / "transcript.json"), cl, wd / "cut.mp4")
    save(wd / "cut_points.json", segs)
    data = transcribe(wd / "cut.mp4", wd / "transcript.cut.json", a.engine)
    print(f"✓ cut.mp4 ({data['duration']:.2f}s, {len(segs)} đoạn) + transcript.cut.json")
    for s in data["segments"]:
        print(f"  [{s['start']:6.2f}-{s['end']:6.2f}] {s['text']}")


def cmd_plan_check(a):
    from .plan import check_plan

    r = check_plan(load(workdir(name_of(a.target)) / "edit_plan.json"))
    print(("✓" if r["ok"] else "✗"), "share", r.get("share"), "max_gap", r.get("max_gap"))
    for e in r["errors"]:
        print("  ERROR", e)
    for w in r["warnings"]:
        print("  warn ", w)
    if not r["ok"]:
        raise SystemExit(1)


def cmd_matte(a):
    from .matte import matte

    wd = workdir(name_of(a.target))
    s = matte(wd / "cut.mp4", wd / "person.webm", wd / "head_track.json")
    print("✓", {k: v for k, v in s.items() if k != "track"})


def cmd_compose(a):
    from .compose import compose
    from .render import hf

    print("✓", compose(name_of(a.target)))
    r = hf("check", str(workdir(name_of(a.target)) / "hf"))
    print(r.stdout[-1500:] if r.returncode else "✓ hyperframes check passed")


def cmd_render(a):
    from .render import render

    render(name_of(a.target), a.quality)


def cmd_qa(a):
    from .qa import qa

    r = qa(name_of(a.target))
    print(("✓ QA passed" if r["ok"] else "✗ QA failed"), r["info"])
    for e in r["errors"]:
        print("  ERROR", e)
    for w in r["warnings"]:
        print("  warn ", w)
    print("  sheets:", *r["sheets"], sep="\n    ")
    if not r["ok"]:
        raise SystemExit(1)


def cmd_build(a):
    """Everything after edit_plan.json exists: plan-check -> matte (if needed) -> compose -> render -> qa."""
    wd = workdir(name_of(a.target))
    cmd_plan_check(a)
    if not (wd / "person.webm").exists() or (wd / "person.webm").stat().st_mtime < (wd / "cut.mp4").stat().st_mtime:
        cmd_matte(a)
    cmd_compose(a)
    cmd_render(a)
    cmd_qa(a)


def main():
    p = argparse.ArgumentParser(prog="autoedit")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in [("transcribe", cmd_transcribe), ("cutlist", cmd_cutlist), ("cut", cmd_cut),
                     ("plan-check", cmd_plan_check), ("matte", cmd_matte), ("compose", cmd_compose),
                     ("render", cmd_render), ("qa", cmd_qa), ("build", cmd_build)]:
        sp = sub.add_parser(name)
        sp.add_argument("target")
        sp.add_argument("--engine", choices=["mlx", "pho"], default="mlx")
        sp.add_argument("--quality", choices=["draft", "looks", "delivery"], default="looks")
        sp.set_defaults(fn=fn)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
