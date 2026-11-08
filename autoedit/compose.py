"""Step 3b: edit_plan.json + transcript.cut.json + head_track.json -> HyperFrames project (work/<name>/hf).

Layer order (z-index): background (1) < head text (2) < person cutout (3) < logos (4)
                       < motion-graphic scenes (5) < captions (6)
Background, head text, person and logos live inside #stage, so zooms move them together.
"""
from __future__ import annotations

import html
import json
import re
import shutil
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

from .common import FPS, H, ROOT, W, load, run, save
from .plan import scenes_of

GSAP = "https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/gsap.min.js"
LOGO_COLORS = {"claude": "#D97757", "ffmpeg": "#007808", "openai": "#111111", "anthropic": "#191919"}


# --------------------------------------------------------------------------- helpers
def esc(s: str) -> str:
    return html.escape(s, quote=True)


@lru_cache(maxsize=64)
def _font(weight: str, size: int):
    st = load(ROOT / "config" / "style.json")
    return ImageFont.truetype(str(ROOT / st["fonts"][weight]), size)


def text_w(text: str, weight: str, size: int, tracking: float = 0.0) -> float:
    return _font(weight, size).getlength(text) + tracking * size * max(0, len(text) - 1)


def fit(text: str, weight: str, base: int, minimum: int, max_w: float, tracking: float = 0.0) -> int:
    s = base
    while s > minimum and text_w(text, weight, s, tracking) > max_w:
        s -= 2
    return s


def metrics(weight: str, size: int) -> tuple[int, int]:
    return _font(weight, size).getmetrics()  # ascent, descent (px)


def font_face(style: dict, prefix: str = "assets/fonts") -> str:
    out = []
    for wt, path in style["fonts"].items():
        out.append(f"@font-face{{font-family:'{style['font_family']}';font-weight:{wt};"
                   f"src:url('{prefix}/{Path(path).name}') format('truetype');font-display:block;}}")
    return "\n".join(out)


def r3(x: float) -> float:
    return round(x, 3)


# --------------------------------------------------------------------------- assets
def _logo_file(name: str) -> Path:
    hits = sorted((ROOT / "media" / "logos").glob(f"{name}.*"))
    if not hits:
        raise FileNotFoundError(f"logo {name} missing in media/logos")
    return hits[0]


def copy_assets(wd: Path, hf: Path, plan: dict, style: dict) -> None:
    a = hf / "assets"
    (a / "fonts").mkdir(parents=True, exist_ok=True)
    (a / "logos").mkdir(parents=True, exist_ok=True)
    for p in style["fonts"].values():
        shutil.copy2(ROOT / p, a / "fonts" / Path(p).name)
    shutil.copy2(ROOT / plan["background"], a / "background.jpg")
    if not (a / "person.webm").exists() or (a / "person.webm").stat().st_mtime < (wd / "person.webm").stat().st_mtime:
        shutil.copy2(wd / "person.webm", a / "person.webm")
    run(["ffmpeg", "-v", "error", "-y", "-i", str(wd / "cut.mp4"), "-vn", "-c:a", "copy", str(a / "voice.m4a")])
    for lg in (ROOT / "media" / "logos").iterdir():
        if lg.suffix == ".svg":
            svg = lg.read_text()
            color = LOGO_COLORS.get(lg.stem)
            if color and "fill=" not in svg.split(">", 1)[0]:
                svg = svg.replace("<svg ", f'<svg fill="{color}" ', 1)
            (a / "logos" / lg.name).write_text(svg)
        elif lg.suffix in (".png", ".jpg", ".webp"):
            shutil.copy2(lg, a / "logos" / lg.name)


# --------------------------------------------------------------------------- geometry from the matte
def head_geometry(track: dict, style: dict):
    frames = track["track"]

    def window(t0: float, t1: float) -> dict:
        f0, f1 = int(t0 * FPS), max(int(t0 * FPS) + 1, int(t1 * FPS))
        sel = frames[f0:f1] or frames[-1:]
        return {"top": min(f["head_top"] for f in sel),
                "cx": int(sum(f["head_cx"] for f in sel) / len(sel))}
    return window


# --------------------------------------------------------------------------- captions
def caption_groups(words: list[dict], n: int) -> list[list[dict]]:
    groups, cur = [], []
    for k, w in enumerate(words):
        cur.append(w)
        nxt = words[k + 1] if k + 1 < len(words) else None
        brk = (len(cur) >= n or re.search(r"[.?!,…]$", w["text"]) or
               (nxt is not None and nxt["start"] - w["end"] >= 0.15))
        if brk or nxt is None:
            groups.append(cur)
            cur = []
    return groups


def clean_word(t: str) -> str:
    return re.sub(r"[.,…]+$", "", t)


def build_captions(words, scenes, geo, style, D) -> tuple[str, list[dict]]:
    cs = style["caption"]
    fam = style["font_family"]
    groups = caption_groups(words, cs["words_per_group"])
    shift = style["split_shift"]
    divs, js, boxes = [], [], []
    for gi, g in enumerate(groups):
        start = 0.12 if gi == 0 else max(g[0]["start"] - 0.05, boxes[-1]["end"])
        nxt_start = groups[gi + 1][0]["start"] - 0.05 if gi + 1 < len(groups) else D
        end = min(max(g[-1]["end"] + 0.25, start + 0.4), nxt_start, D - 0.02)
        text = " ".join(clean_word(w["text"]) for w in g)
        size = fit(text, "800", cs["base_size"], cs["min_size"], cs["max_width"] / 1.1 - 0.4 * cs["base_size"] * (len(g) - 1))
        asc, desc = metrics("800", size)
        h = int((asc + desc) * 1.05)
        mid = start + min(0.25, (end - start) / 2)
        lay = next((s["layout"] for s in scenes if s["t"] <= mid < s["end"]), "normal")
        if lay == "split":
            hg = geo(start, end)
            bottom = min(cs["y_split_max"] + h / 2, hg["top"] + shift - cs["gap_above_head"])
            top = bottom - h
        elif lay == "fullscreen":
            top = cs["y_fullscreen"] - h / 2
        else:
            top = cs["y_normal"] - h / 2
        gid = f"cg{gi}"
        spans = "".join(f'<span class="cw" id="{gid}w{k}">{esc(clean_word(w["text"]))}</span>'
                        for k, w in enumerate(g))
        divs.append(f'<div id="{gid}" class="clip cgroup" data-start="{r3(start)}" data-duration="{r3(end - start)}" '
                    f'data-track-index="0" style="top:{top:.0f}px;height:{h}px;font-size:{size}px;line-height:{h}px">'
                    f'<div class="cg-in" id="{gid}i">{spans}</div></div>')
        js.append(f'tl.fromTo("#{gid}i",{{opacity:0,y:22,scale:0.94}},{{opacity:1,y:0,scale:1,duration:0.18,ease:"back.out(2)"}},{r3(start)});')
        for k, w in enumerate(g):
            ws = max(start, w["start"])
            we = g[k + 1]["start"] if k + 1 < len(g) else end
            js.append(f'tl.set("#{gid}w{k}",{{color:"{style["colors"]["accent"]}",scale:1.1}},{r3(ws)});')
            if k + 1 < len(g):
                js.append(f'tl.set("#{gid}w{k}",{{color:"#FFFFFF",scale:1}},{r3(we)});')
        js.append(f'tl.to("#{gid}i",{{opacity:0,y:-10,duration:0.12,ease:"power2.in"}},{r3(end - 0.13)});')
        js.append(f'tl.set("#{gid}i",{{opacity:0}},{r3(end - 0.01)});')
        boxes.append({"id": gid, "start": r3(start), "end": r3(end), "top": round(top), "bottom": round(top + h),
                      "width": round(text_w(text, "800", size) * 1.1), "layout": lay, "text": text})
    stroke = ",".join(f"{x}px {y}px 0 #000" for x, y in
                      [(-4, 0), (4, 0), (0, -4), (0, 4), (-3, -3), (3, -3), (-3, 3), (3, 3)])
    doc = f"""<template>
  <style>
    {font_face(style)}
    #root {{ position:absolute; inset:0; pointer-events:none; }}
    .cgroup {{ position:absolute; left:0; width:100%; text-align:center; overflow:visible;
      font-family:'{fam}'; font-weight:800; color:#fff; white-space:nowrap;
      text-shadow:{stroke},0 8px 22px rgba(0,0,0,.65); }}
    .cg-in {{ opacity:0; }}
    .cw {{ display:inline-block; margin:0 0.2em; transform-origin:50% 60%; }}
  </style>
  <div id="root" data-composition-id="captions" data-width="{W}" data-height="{H}">
    {''.join(divs)}
  </div>
  <script>
    const tl = gsap.timeline({{ paused: true }});
    {chr(10).join(js)}
    window.__timelines["captions"] = tl;
  </script>
</template>
"""
    return doc, boxes


# --------------------------------------------------------------------------- motion graphics
def _logo_tile(name: str, size: int) -> str:
    f = _logo_file(name)
    return (f'<span class="tile" style="width:{size}px;height:{size}px">'
            f'<img src="assets/logos/{f.name}" alt="{esc(name)}"/></span>')


def mg_scene(sid: str, sc: dict, style: dict, area: tuple[int, int], exit_kind: str) -> str:
    """One sub-composition per split / fullscreen scene. Times inside are local to the scene."""
    mg, lay, t0, dur = sc["mg"], sc["layout"], sc["t"], sc["end"] - sc["t"]
    c = style["colors"]
    fam = style["font_family"]
    T = style["transition_dur"]
    loc = lambda t: r3(max(0.05, t - t0))  # noqa: E731
    top, bottom = area
    body, js = [], []
    tpl = mg["template"]

    # ---- content per template
    if tpl in ("list", "steps"):
        items = mg["items"]
        n = len(items)
        title_size = 64 if lay == "split" else 84
        row_h = min(120, int((bottom - top - title_size - 110) / max(1, n)))
        y = 36
        body.append(f'<div class="mg-title" id="{sid}-title" style="top:{y}px;font-size:{title_size}px">{esc(mg["title"])}</div>')
        y += title_size + 40
        for k, it in enumerate(items):
            if it.get("logo"):
                icon = _logo_tile(it["logo"], row_h - 28)
            elif tpl == "steps":
                last = k == n - 1
                icon = (f'<span class="badge" style="width:{row_h - 28}px;height:{row_h - 28}px;'
                        f'background:{"#22C55E" if last else c["accent"]}">{"✓" if last else k + 1}</span>')
            else:
                icon = f'<span class="badge" style="width:{row_h - 28}px;height:{row_h - 28}px">•</span>'
            fs = fit(it["text"], "800", 50 if lay == "split" else 60, 34, 860 - row_h)
            body.append(f'<div class="row" id="{sid}-r{k}" style="top:{y}px;height:{row_h}px">{icon}'
                        f'<span class="row-text" style="font-size:{fs}px">{esc(it["text"])}</span></div>')
            js.append(f'tl.fromTo("#{sid}-r{k}",{{opacity:0,x:-60}},{{opacity:1,x:0,duration:0.45,ease:"power3.out"}},{loc(it["at"])});')
            js.append(f'tl.fromTo("#{sid}-r{k} .tile, #{sid}-r{k} .badge",{{scale:0.4,rotation:-12}},{{scale:1,rotation:0,duration:0.5,ease:"back.out(2.2)"}},{loc(it["at"])});')
            if k:
                js.append(f'tl.to("#{sid}-r{k - 1}",{{opacity:0.55,duration:0.3}},{loc(it["at"])});')
            y += row_h + 14
        js.insert(0, f'tl.fromTo("#{sid}-title",{{opacity:0,y:-30}},{{opacity:1,y:0,duration:0.5,ease:"power3.out"}},{r3(T * 0.6)});')
        content_h = y + 20
    elif tpl == "flow":
        nodes = mg["nodes"]
        title_size = 76
        body.append(f'<div class="mg-title" id="{sid}-title" style="top:0px;font-size:{title_size}px">{esc(mg["title"])}</div>')
        js.append(f'tl.fromTo("#{sid}-title",{{opacity:0,y:-30}},{{opacity:1,y:0,duration:0.5,ease:"power3.out"}},{r3(T * 0.6)});')
        y, node_h, gap = title_size + 70, 150, 64
        for k, nd in enumerate(nodes):
            if k:
                body.append(f'<div class="arrow" id="{sid}-a{k}" style="top:{y - gap + 8}px;height:{gap - 16}px"></div>')
                js.append(f'tl.fromTo("#{sid}-a{k}",{{scaleY:0}},{{scaleY:1,duration:0.3,ease:"power2.out"}},{r3(loc(nd["at"]) - 0.2)});')
            logos = "".join(_logo_tile(l, 78) for l in nd.get("logos", []))
            body.append(f'<div class="node" id="{sid}-n{k}" style="top:{y}px;height:{node_h}px">'
                        f'<div class="node-txt"><div class="node-label">{esc(nd["label"])}</div>'
                        f'<div class="node-sub">{esc(nd.get("sub", ""))}</div></div>'
                        f'<div class="node-logos">{logos}</div></div>')
            js.append(f'tl.fromTo("#{sid}-n{k}",{{opacity:0,scale:0.88,y:30}},{{opacity:1,scale:1,y:0,duration:0.45,ease:"back.out(1.8)"}},{loc(nd["at"])});')
            js.append(f'tl.fromTo("#{sid}-n{k}",{{borderColor:"{c["accent"]}"}},{{borderColor:"rgba(255,255,255,0.18)",duration:0.4}},{r3(loc(nodes[k + 1]["at"]) if k + 1 < len(nodes) else dur - 0.2)});')
            y += node_h + gap
        content_h = y - gap
    elif tpl == "strike":
        tsize = fit(mg["title"], "900", 96, 52, 900)
        body.append(f'<div class="kicker" id="{sid}-k" style="top:0px">{esc(mg.get("kicker", ""))}</div>')
        body.append(f'<div class="strike-wrap" id="{sid}-sw" style="top:90px">'
                    f'<div class="strike-title" style="font-size:{tsize}px">{esc(mg["title"])}</div>'
                    f'<div class="strike-line" id="{sid}-line"></div></div>')
        body.append(f'<div class="stamp" id="{sid}-stamp" style="top:{90 + int(tsize * 1.3) + 110}px">{esc(mg["stamp"])}</div>')
        body.append(f'<div class="mg-sub" id="{sid}-sub" style="top:{90 + int(tsize * 1.3) + 330}px">{esc(mg.get("sub", ""))}</div>')
        js += [
            f'tl.fromTo("#{sid}-k",{{opacity:0,y:-20}},{{opacity:1,y:0,duration:0.4,ease:"power3.out"}},{r3(T * 0.6)});',
            f'tl.fromTo("#{sid}-sw",{{opacity:0,scale:0.9}},{{opacity:1,scale:1,duration:0.5,ease:"back.out(1.6)"}},{r3(T * 0.8)});',
            f'tl.fromTo("#{sid}-line",{{scaleX:0}},{{scaleX:1,duration:0.35,ease:"power3.inOut"}},{loc(mg["strike_at"])});',
            f'tl.to("#{sid}-sw .strike-title",{{opacity:0.45,duration:0.3}},{loc(mg["strike_at"]) + 0.2});',
            f'tl.fromTo("#{sid}-stamp",{{opacity:0,scale:2.4,rotation:-18}},{{opacity:1,scale:1,rotation:-8,duration:0.35,ease:"power4.out"}},{r3(loc(mg["strike_at"]) + 0.3)});',
            f'tl.fromTo("#{sid}-sub",{{opacity:0,y:30}},{{opacity:1,y:0,duration:0.45,ease:"power3.out"}},{loc(mg.get("sub_at", mg["strike_at"] + 1))});',
        ]
        content_h = 90 + int(tsize * 1.3) + 420
    else:  # title / stat / icon_title
        main = mg.get("value") or mg.get("title", "")
        sub = mg.get("label") or mg.get("sub", "")
        ms = fit(main, "900", 200 if tpl == "stat" else 110, 60, 920)
        body.append(f'<div class="mg-title" id="{sid}-title" style="top:0px;font-size:{ms}px;color:{c["accent"] if tpl == "stat" else "#fff"}">{esc(main)}</div>')
        body.append(f'<div class="mg-sub" id="{sid}-sub" style="top:{int(ms * 1.4)}px">{esc(sub)}</div>')
        js += [f'tl.fromTo("#{sid}-title",{{opacity:0,scale:0.8}},{{opacity:1,scale:1,duration:0.5,ease:"back.out(2)"}},{r3(T * 0.6)});',
               f'tl.fromTo("#{sid}-sub",{{opacity:0,y:20}},{{opacity:1,y:0,duration:0.4}},{r3(T + 0.4)});']
        content_h = int(ms * 1.4) + 120

    # ---- panel + transitions
    if lay == "fullscreen":
        content_top = max(top, int((top + bottom) / 2 - content_h / 2))
        panel = (f'<div class="fs-bg"></div><div class="fs-grid"></div><div class="fs-glow"></div>'
                 f'<div class="content" id="{sid}-content" style="top:{content_top}px">{"".join(body)}</div>')
        tin = sc.get("transition", "zoom-blur")
        if tin == "wipe":
            js.insert(0, f'tl.fromTo("#{sid}-panel",{{clipPath:"circle(0% at 50% 45%)"}},{{clipPath:"circle(150% at 50% 45%)",duration:{T + 0.1},ease:"power2.inOut"}},0);')
        else:
            js.insert(0, f'tl.fromTo("#{sid}-panel",{{opacity:0,scale:1.18,filter:"blur(18px)"}},{{opacity:1,scale:1,filter:"blur(0px)",duration:{T},ease:"power3.out"}},0);')
        if exit_kind == "wipe":
            js.append(f'tl.fromTo("#{sid}-panel",{{clipPath:"circle(150% at 50% 45%)"}},{{clipPath:"circle(0% at 50% 45%)",duration:{T},ease:"power2.in"}},{r3(dur - T)});')
        elif exit_kind == "slide-up":
            js.append(f'tl.to("#{sid}-panel",{{y:-{H},duration:{T},ease:"power3.in"}},{r3(dur - T)});')
        else:
            js.append(f'tl.to("#{sid}-panel",{{opacity:0,scale:1.08,filter:"blur(14px)",duration:{T},ease:"power2.in"}},{r3(dur - T)});')
    else:  # split: glass card in the space above the head
        card_h = min(bottom - top, content_h + 30)
        panel = (f'<div class="card" id="{sid}-card" style="top:{top}px;height:{card_h}px">'
                 f'<div class="content" id="{sid}-content" style="top:0px">{"".join(body)}</div></div>')
        tin = sc.get("transition", "slide-down")
        if tin == "wipe":
            js.insert(0, f'tl.fromTo("#{sid}-card",{{clipPath:"inset(0% 100% 0% 0% round 36px)"}},{{clipPath:"inset(0% 0% 0% 0% round 36px)",duration:{T + 0.1},ease:"power3.inOut"}},0);')
        else:
            js.insert(0, f'tl.fromTo("#{sid}-card",{{opacity:0,y:-120,scale:0.96}},{{opacity:1,y:0,scale:1,duration:{T + 0.1},ease:"power3.out"}},0);')
        js.append(f'tl.to("#{sid}-card",{{opacity:0,y:-90,scale:0.96,duration:{T},ease:"power2.in"}},{r3(dur - T)});')
    js.append(f'tl.set("#{sid}-panel",{{opacity:0}},{r3(dur - 0.01)});')

    tile_css = ".tile{display:inline-flex;align-items:center;justify-content:center;background:#fff;border-radius:22%;box-shadow:0 8px 24px rgba(0,0,0,.35);flex:none}.tile img{width:70%;height:70%;object-fit:contain}"
    return f"""<template>
  <style>
    {font_face(style)}
    #root {{ position:absolute; inset:0; font-family:'{fam}'; color:#fff; }}
    #{sid}-panel {{ position:absolute; inset:0; transform-origin:50% 45%; }}
    .fs-bg {{ position:absolute; inset:0; background:radial-gradient(120% 80% at 50% 30%, {c["bg_dark2"]} 0%, {c["bg_dark"]} 70%); }}
    .fs-grid {{ position:absolute; inset:0; opacity:.16; background-image:linear-gradient(rgba(255,255,255,.35) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.35) 1px,transparent 1px); background-size:72px 72px; }}
    .fs-glow {{ position:absolute; left:140px; top:260px; width:800px; height:800px; border-radius:50%; background:radial-gradient(circle, rgba(79,140,255,.35), rgba(79,140,255,0) 70%); }}
    .card {{ position:absolute; left:40px; right:40px; border-radius:36px; background:rgba(10,15,36,.80);
      border:2px solid rgba(255,255,255,.14); box-shadow:0 24px 60px rgba(0,0,0,.45); overflow:hidden; }}
    .content {{ position:absolute; left:0; right:0; }}
    .mg-title {{ position:absolute; left:60px; right:60px; text-align:center; font-weight:900; line-height:1.15;
      text-shadow:0 6px 18px rgba(0,0,0,.5); text-wrap:balance; }}
    .mg-sub {{ position:absolute; left:60px; right:60px; text-align:center; font-weight:700; font-size:50px; color:{c["accent"]}; }}
    .row {{ position:absolute; left:60px; right:60px; display:flex; align-items:center; gap:28px; }}
    .row-text {{ font-weight:800; line-height:1.2; text-shadow:0 4px 12px rgba(0,0,0,.4); }}
    .badge {{ display:inline-flex; align-items:center; justify-content:center; border-radius:50%; background:{c["accent2"]};
      color:#0A0F24; font-weight:900; font-size:44px; flex:none; }}
    {tile_css}
    .node {{ position:absolute; left:120px; right:120px; border-radius:30px; background:rgba(255,255,255,.07);
      border:3px solid rgba(255,255,255,.18); display:flex; align-items:center; justify-content:space-between; padding:0 40px; }}
    .node-label {{ font-weight:800; font-size:52px; line-height:1.15; }}
    .node-sub {{ font-weight:600; font-size:32px; color:{c["accent"]}; margin-top:6px; }}
    .node-logos {{ display:flex; gap:16px; }}
    .arrow {{ position:absolute; left:536px; width:8px; border-radius:4px; background:{c["accent"]}; transform-origin:50% 0%; }}
    .arrow::after {{ content:''; position:absolute; left:-14px; bottom:-14px; border-left:18px solid transparent;
      border-right:18px solid transparent; border-top:22px solid {c["accent"]}; }}
    .kicker {{ position:absolute; left:0; right:0; text-align:center; font-weight:800; font-size:44px; letter-spacing:.06em;
      text-transform:uppercase; color:{c["accent"]}; }}
    .strike-wrap {{ position:absolute; left:60px; right:60px; }}
    .strike-title {{ text-align:center; font-weight:900; line-height:1.15; white-space:nowrap; }}
    .strike-line {{ position:absolute; left:-10px; right:-10px; top:46%; height:14px; border-radius:7px; background:{c["danger"]};
      transform-origin:0% 50%; box-shadow:0 4px 16px rgba(255,77,94,.6); }}
    .stamp {{ position:absolute; left:50%; margin-left:-230px; width:460px; text-align:center; font-weight:900; font-size:86px;
      color:{c["danger"]}; border:10px solid {c["danger"]}; border-radius:24px; padding:6px 0; }}
  </style>
  <div id="root" data-composition-id="{sid}" data-width="{W}" data-height="{H}">
    <div id="{sid}-panel">{panel}</div>
  </div>
  <script>
    const tl = gsap.timeline({{ paused: true }});
    {chr(10).join(js)}
    window.__timelines["{sid}"] = tl;
  </script>
</template>
"""


def max_zoom(plan: dict, t0: float, t1: float) -> float:
    """Largest stage scale reached in [t0, t1] (zoom targets as steps; 'hold' returns to 1)."""
    steps = []
    for e in sorted((e for e in plan["events"] if e["type"] == "zoom"), key=lambda e: e["t"]):
        p = e["params"]
        steps.append((e["t"], p["to"]))
        if p.get("hold"):
            steps.append((e["t"] + p["dur"] + p["hold"], 1.0))
    steps.sort()
    cur, best = 1.0, 1.0
    for t, v in steps:
        if t <= t0:
            cur = v
        elif t < t1:
            best = max(best, v)
    return max(best, cur)


# --------------------------------------------------------------------------- root
def compose(name: str) -> dict:
    wd = ROOT / "work" / name
    hf = wd / "hf"
    (hf / "compositions").mkdir(parents=True, exist_ok=True)
    plan = load(wd / "edit_plan.json")
    tr = load(wd / "transcript.cut.json")
    track = load(wd / "head_track.json")
    style = load(ROOT / "config" / "style.json")
    copy_assets(wd, hf, plan, style)
    D = r3(plan["duration"])
    scenes = scenes_of(plan)
    geo = head_geometry(track, style)
    shift = style["split_shift"]
    hs = style["head_text"]
    c = style["colors"]
    fam = style["font_family"]
    T = style["transition_dur"]

    body, js, layout = [], [], {"scenes": scenes, "head_texts": [], "logos": []}

    # --- head texts (behind the head)
    for k, e in enumerate([e for e in plan["events"] if e["type"] == "head_text"]):
        p, t = e["params"], e["t"]
        g = geo(t, t + p["dur"])
        zmax = max_zoom(plan, t, t + p["dur"])
        size = fit(p["text"], "900", hs["base_size"], hs["min_size"], hs["max_width"] / zmax, -0.02)
        asc, desc = metrics("900", size)
        cap = 0.72 * size
        baseline = g["top"] + hs["cover_ratio"] * cap + 0.1 * size
        top_main = baseline - asc
        sub = p.get("sub", "")
        sub_size = fit(sub, "800", 64, 36, 900, 0.08) if sub else 0
        sub_top = baseline - cap - 0.30 * size - sub_size * 1.45
        words = []
        for w in p["text"].split():
            col = c["accent"] if w in p.get("accent", []) else "#fff"
            words.append(f'<span style="color:{col}">{esc(w)}</span>')
        hid = f"ht{k}"
        body.append(
            f'<div id="{hid}" class="clip ht" data-start="{r3(t)}" data-duration="{r3(p["dur"])}" data-track-index="2">'
            f'<div class="ht-in" id="{hid}-in">'
            + (f'<div class="ht-sub" style="top:{sub_top:.0f}px;font-size:{sub_size}px">{esc(sub)}</div>' if sub else "")
            + f'<div class="ht-main" style="top:{top_main:.0f}px;font-size:{size}px;line-height:{asc + desc}px">{" ".join(words)}</div>'
            f'</div></div>')
        js += [
            f'tl.fromTo("#{hid}-in .ht-main",{{opacity:0,y:60,scale:0.9,filter:"blur(14px)"}},{{opacity:1,y:0,scale:1,filter:"blur(0px)",duration:0.55,ease:"power3.out"}},{r3(t)});',
            f'tl.fromTo("#{hid}-in .ht-sub",{{opacity:0,y:-24,scaleX:1.25}},{{opacity:1,y:0,scaleX:1,duration:0.6,ease:"power3.out"}},{r3(t + 0.12)});',
            f'tl.to("#{hid}-in",{{opacity:0,y:-30,filter:"blur(10px)",duration:0.4,ease:"power2.in"}},{r3(t + p["dur"] - 0.42)});',
        ]
        layout["head_texts"].append({"id": hid, "t": t, "end": t + p["dur"], "top": round(sub_top if sub else top_main),
                                     "baseline": round(baseline), "head_top": g["top"], "size": size})

    # --- logos beside the head
    for k, e in enumerate([e for e in plan["events"] if e["type"] == "logo"]):
        p, t = e["params"], e["t"]
        g = geo(t, t + p["dur"])
        lid = f"lg{k}"
        x = {"top-left": 70, "top-right": W - 70 - 170}.get(p.get("pos"), min(W - 200, g["cx"] + 250))
        y = {"top-left": 220, "top-right": 220}.get(p.get("pos"), g["top"] + 60)
        f = _logo_file(p["name"])
        body.append(f'<div id="{lid}" class="clip logo" data-start="{r3(t)}" data-duration="{r3(p["dur"])}" data-track-index="4" '
                    f'style="left:{x}px;top:{y}px"><div class="logo-in" id="{lid}-in"><img src="assets/logos/{f.name}" alt="{esc(p["name"])}"/></div></div>')
        js += [f'tl.fromTo("#{lid}-in",{{opacity:0,scale:0.4,rotation:-14}},{{opacity:1,scale:1,rotation:0,duration:0.45,ease:"back.out(2.4)"}},{r3(t)});',
               f'tl.to("#{lid}-in",{{opacity:0,scale:0.6,duration:0.3,ease:"power2.in"}},{r3(t + p["dur"] - 0.32)});']
        layout["logos"].append({"id": lid, "t": t, "x": x, "y": y})

    # --- zooms (stage), forced back to 1 when a split / fullscreen starts
    g0 = geo(0, D)
    origin = f"{g0['cx']}px {g0['top'] + 300}px"
    zooms = sorted([e for e in plan["events"] if e["type"] == "zoom"], key=lambda e: e["t"])
    for e in zooms:
        p = e["params"]
        js.append(f'tl.to("#stage",{{scale:{p["to"]},duration:{p["dur"]},ease:"{p.get("ease", "power2.out")}"}},{r3(e["t"])});')
        if p.get("hold"):
            js.append(f'tl.to("#stage",{{scale:1,duration:{p["dur"] + 0.15},ease:"power2.inOut"}},{r3(e["t"] + p["dur"] + p["hold"])});')
    def scale_before(t):
        sc = 1.0
        for e in zooms:
            p = e["params"]
            if e["t"] >= t:
                break
            sc = 1.0 if p.get("hold") else p["to"]
        return sc
    for s in scenes:
        if s["layout"] == "split" and scale_before(s["t"]) != 1.0:
            js.append(f'tl.to("#stage",{{scale:1,duration:0.4,ease:"power2.inOut"}},{r3(max(0, s["t"] - 0.2))});')
        elif s["layout"] == "fullscreen":
            js.append(f'tl.set("#stage",{{scale:1}},{r3(s["t"] + T + 0.05)});')

    # --- person position per scene (split = pulled down by split_shift)
    prev_y = 0
    for i, s in enumerate(scenes):
        target = shift if s["layout"] == "split" else prev_y if s["layout"] == "fullscreen" else 0
        if s["layout"] == "fullscreen":
            nxt = scenes[i + 1] if i + 1 < len(scenes) else None
            nt = shift if nxt and nxt["layout"] == "split" else 0
            if nt != prev_y:  # move while hidden behind the full-screen panel
                js.append(f'tl.set("#personWrap",{{y:{nt}}},{r3(s["t"] + T + 0.1)});')
            prev_y = nt
            continue
        if target != prev_y:
            js.append(f'tl.to("#personWrap",{{y:{target},duration:0.6,ease:"power3.inOut"}},{r3(max(0, s["t"] - 0.15))});')
        prev_y = target

    # --- background Ken Burns
    kb0, kb1 = style["background_kenburns"]
    js.insert(0, f'tl.fromTo("#bg",{{scale:{kb0}}},{{scale:{kb1},duration:{D},ease:"none"}},0);')

    # --- motion-graphic scene hosts
    hosts = []
    for i, s in enumerate(scenes):
        if s["layout"] == "normal":
            continue
        sid = f"mg{i}"
        if s["layout"] == "split":
            gs = geo(s["t"], s["end"])
            cap_top = min(style["caption"]["y_split_max"], gs["top"] + shift - style["caption"]["gap_above_head"]) - 110
            area = (190, int(cap_top - 24))
        else:
            area = (260, 1400)
        nxt = scenes[i + 1] if i + 1 < len(scenes) else None
        exit_kind = nxt["transition"] if nxt else "fade"
        (hf / "compositions" / f"{sid}.html").write_text(mg_scene(sid, s, style, area, exit_kind), encoding="utf-8")
        hosts.append(f'<div id="{sid}" data-composition-id="{sid}" data-composition-src="compositions/{sid}.html" '
                     f'data-start="{r3(s["t"])}" data-duration="{r3(s["end"] - s["t"])}" data-track-index="5" '
                     f'data-track-kind="graphics" data-width="{W}" data-height="{H}" style="z-index:5"></div>')
        s["mg_area"] = area

    # --- captions
    cap_doc, boxes = build_captions(tr["words"], scenes, geo, style, D)
    (hf / "compositions" / "captions.html").write_text(cap_doc, encoding="utf-8")
    layout["captions"] = boxes

    index = f"""<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width={W}, height={H}" />
  <script src="{GSAP}"></script>
  <style>
    {font_face(style)}
    html, body {{ margin:0; background:#000; }}
    #root {{ position:relative; width:{W}px; height:{H}px; overflow:hidden; background:#0A0F24; font-family:'{fam}'; }}
    #stage {{ position:absolute; left:0; top:0; width:{W}px; height:{H}px; transform-origin:{origin}; }}
    #bg {{ position:absolute; left:-54px; top:-96px; width:1188px; height:2112px; object-fit:cover; z-index:1; }}
    .ht {{ position:absolute; left:0; top:0; width:{W}px; height:{H}px; z-index:2; }}
    .ht-in {{ position:absolute; inset:0; }}
    .ht-main {{ position:absolute; left:0; width:100%; text-align:center; font-weight:900; letter-spacing:-0.02em; white-space:nowrap;
      text-shadow:0 4px 0 rgba(0,0,0,.25), 0 10px 30px rgba(0,0,0,.55), 0 0 60px rgba(0,0,0,.35); }}
    .ht-sub {{ position:absolute; left:0; width:100%; text-align:center; font-weight:800; letter-spacing:.08em; color:{c["accent"]};
      white-space:nowrap; text-shadow:0 4px 16px rgba(0,0,0,.6); }}
    #personWrap {{ position:absolute; left:0; top:0; width:{W}px; height:{H}px; z-index:3; }}
    #person {{ position:absolute; left:0; top:0; width:{W}px; height:{H}px; object-fit:cover; }}
    .logo {{ position:absolute; width:170px; height:170px; z-index:4; }}
    .logo-in {{ width:100%; height:100%; border-radius:38px; background:#fff; display:flex; align-items:center; justify-content:center;
      box-shadow:0 14px 40px rgba(0,0,0,.45); }}
    .logo-in img {{ width:68%; height:68%; object-fit:contain; }}
  </style>
</head>
<body>
  <div id="root" data-composition-id="main" data-start="0" data-duration="{D}" data-width="{W}" data-height="{H}" data-fps="{FPS}">
    <div id="stage">
      <img id="bg" src="assets/background.jpg" alt="" />
      {chr(10).join(b for b in body if 'class="clip ht"' in b)}
      <div id="personWrap">
        <video id="person" class="clip" data-start="0" data-duration="{D}" data-track-index="3" src="assets/person.webm"
          muted playsinline data-layout-allow-occlusion></video>
      </div>
      {chr(10).join(b for b in body if 'class="clip logo"' in b)}
    </div>
    {chr(10).join(hosts)}
    <div id="captions" data-composition-id="captions" data-composition-src="compositions/captions.html" data-start="0"
      data-duration="{D}" data-track-index="6" data-track-kind="captions" data-width="{W}" data-height="{H}" style="z-index:6"></div>
    <audio id="voice" class="clip" data-start="0" data-duration="{D}" data-track-index="7" data-volume="1" src="assets/voice.m4a"></audio>
  </div>
  <script>
    const tl = gsap.timeline({{ paused: true }});
    {chr(10).join("    " + j for j in js).strip()}
    window.__timelines = window.__timelines || {{}};
    window.__timelines["main"] = tl;
  </script>
</body>
</html>
"""
    (hf / "index.html").write_text(index, encoding="utf-8")
    save(wd / "layout.json", {**layout, "split_shift": shift, "duration": D})
    return {"dir": str(hf), "scenes": len(scenes), "captions": len(boxes), "head_texts": len(layout["head_texts"])}
