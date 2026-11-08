"""Step 2 helper: validate edit_plan.json written by the director (Claude)."""
from __future__ import annotations

from pathlib import Path

from .common import ROOT

LAYOUTS = {"normal", "split", "fullscreen"}
TRANSITIONS = {"none", "fade", "slide-up", "slide-down", "slide-left", "zoom-blur", "wipe", "push"}
TEMPLATES = {"title", "stat", "steps", "list", "compare", "icon_title", "flow", "strike"}
MAX_GAP = 3.0


def scenes_of(plan: dict) -> list[dict]:
    out = []
    for e in plan["events"]:
        if e["type"] == "scene":
            p = e["params"]
            out.append({"t": e["t"], "end": round(e["t"] + p["dur"], 3), **p})
    return sorted(out, key=lambda s: s["t"])


def layout_at(scenes: list[dict], t: float) -> str:
    for s in scenes:
        if s["t"] <= t < s["end"]:
            return s["layout"]
    return scenes[-1]["layout"]


def change_times(plan: dict) -> list[float]:
    ts = []
    for e in plan["events"]:
        p = e["params"]
        ts.append(e["t"])
        if e["type"] in ("head_text", "logo"):
            ts.append(e["t"] + p["dur"])
        mg = p.get("mg") or {}
        for it in mg.get("items", []) + mg.get("nodes", []):
            ts.append(it["at"])
        for k in ("strike_at", "sub_at"):
            if k in mg:
                ts.append(mg[k])
    return sorted(set(round(t, 2) for t in ts))


def check_plan(plan: dict) -> dict:
    errors, warnings = [], []
    D = plan["duration"]
    sc = scenes_of(plan)
    if not sc:
        errors.append("no scene events")
        return {"ok": False, "errors": errors, "warnings": warnings}
    if abs(sc[0]["t"]) > 1e-3:
        errors.append("first scene must start at 0")
    if abs(sc[-1]["end"] - D) > 0.05:
        errors.append(f"scenes end at {sc[-1]['end']} but duration is {D}")
    for a, b in zip(sc, sc[1:]):
        if abs(a["end"] - b["t"]) > 0.02:
            errors.append(f"gap/overlap between scenes at {a['end']} / {b['t']}")
        if b["transition"] == "none" and a["layout"] != b["layout"]:
            errors.append(f"scene at {b['t']} changes layout without a transition")
    for s in sc:
        if s["layout"] not in LAYOUTS:
            errors.append(f"bad layout {s['layout']}")
        if s["transition"] not in TRANSITIONS:
            errors.append(f"bad transition {s['transition']}")
        if s["layout"] in ("split", "fullscreen"):
            mg = s.get("mg")
            if not mg or mg.get("template") not in TEMPLATES:
                errors.append(f"scene at {s['t']} ({s['layout']}) needs mg with a known template")
    share = {k: sum(s["end"] - s["t"] for s in sc if s["layout"] == k) / D for k in LAYOUTS}
    for k in ("fullscreen", "split"):
        if not 0.20 <= share[k] <= 0.30 + 1e-6:
            errors.append(f"{k} share {share[k]:.1%} outside 20–30%")
    for e in plan["events"]:
        p = e["params"]
        if e["type"] == "head_text":
            lay = layout_at(sc, e["t"] + 0.01)
            if lay != "normal":
                errors.append(f"head_text at {e['t']} is in a {lay} scene")
            if len(p["text"].split()) > 3:
                warnings.append(f"head_text '{p['text']}' has more than 3 words")
            end = e["t"] + p["dur"]
            scene = next(s for s in sc if s["t"] <= e["t"] < s["end"])
            if end > scene["end"] + 0.01:
                errors.append(f"head_text at {e['t']} runs past its scene end {scene['end']}")
        if e["type"] == "logo" and not (ROOT / p["file"]).exists():
            errors.append(f"logo file missing: {p['file']}")
        if e["type"] == "zoom" and not 1.0 <= p["to"] <= 1.25:
            errors.append(f"zoom {p['to']} outside 1.0–1.25")
    for s in sc:
        mg = s.get("mg") or {}
        for it in mg.get("items", []) + mg.get("nodes", []):
            if not s["t"] <= it["at"] < s["end"]:
                errors.append(f"mg item '{it.get('text') or it.get('label')}' at {it['at']} outside its scene")
            for lg in it.get("logos", []) + ([it["logo"]] if it.get("logo") else []):
                if not list((ROOT / "media" / "logos").glob(f"{lg}.*")):
                    errors.append(f"logo '{lg}' not in media/logos")
    ts = change_times(plan) + [D]
    gaps = [(round(b - a, 2), a) for a, b in zip(ts, ts[1:])]
    big = [g for g in gaps if g[0] > MAX_GAP]
    if big:
        warnings.append(f"visual changes more than {MAX_GAP}s apart at: {big}")
    if not plan.get("background") or not (ROOT / plan["background"]).exists():
        errors.append("background image missing")
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "share": {k: round(v, 3) for k, v in share.items()},
            "max_gap": max(g[0] for g in gaps) if gaps else 0, "n_changes": len(ts)}
