"""Step 1b: decide what to remove (fillers, retakes, long silences) -> cut_list.json.

Also holds `compute_keep`, the single place that turns transcript + enabled cuts into
keep intervals (used by both `cutlist` for the preview stats and by `cut`).
"""
from __future__ import annotations

from rapidfuzz import fuzz

from .common import norm, snap

PAD = 0.15
AFADE_MS = 30
SIM_THRESHOLD = 70.0      # % similarity => retake
SILENCE_MAX = 0.8         # pauses longer than this are shortened ...
SILENCE_KEEP = 0.3        # ... to roughly this (pad on both sides)
LOOKAHEAD = 3             # compare a sentence with the next N sentences


def _seg_text(seg: dict, words: list[dict]) -> str:
    return norm(" ".join(words[i]["text"] for i in seg["word_ids"] if not words[i]["filler"]))


def similarity(a: str, b: str) -> float:
    """Full-sentence similarity, or prefix similarity for false starts ('Tại sao một...' vs full line)."""
    if not a or not b:
        return 0.0
    full = fuzz.ratio(a, b)
    aw, bw = a.split(), b.split()
    prefix = 0.0
    if len(aw) >= 3 and len(aw) <= len(bw):
        prefix = fuzz.ratio(a, " ".join(bw[: len(aw)]))
    return max(full, prefix)


def find_retakes(transcript: dict) -> list[dict]:
    words, segs = transcript["words"], transcript["segments"]
    texts = [_seg_text(s, words) for s in segs]
    cuts, dropped = [], set()
    for i, s in enumerate(segs):
        if i in dropped or len(texts[i].split()) < 2:
            continue
        best = None
        for j in range(i + 1, min(len(segs), i + 1 + LOOKAHEAD)):
            sim = similarity(texts[i], texts[j])
            if sim >= SIM_THRESHOLD and (best is None or sim > best[1]):
                best = (j, sim)
        if best:
            j, sim = best
            # keep the later take: drop sentence i and anything between i and j (broken attempts)
            ids = [k for seg in segs[i:j] for k in seg["word_ids"]]
            dropped.update(range(i, j))
            cuts.append({
                "reason": "retake",
                "start": words[ids[0]]["start"], "end": words[ids[-1]]["end"],
                "word_ids": ids,
                "text": " ".join(words[k]["text"] for k in ids),
                "similar_to": f"s{segs[j]['id']}", "kept_text": segs[j]["text"],
                "similarity": round(sim / 100, 2),
            })
    return cuts


def find_fillers(transcript: dict, taken: set[int]) -> list[dict]:
    return [{"reason": "filler", "start": w["start"], "end": w["end"], "word_ids": [w["i"]], "text": w["text"]}
            for w in transcript["words"] if w["filler"] and w["i"] not in taken]


def removed_words(transcript: dict, cuts: list[dict]) -> set[int]:
    gone: set[int] = set()
    for c in cuts:
        if not c.get("enabled", True):
            continue
        if c.get("word_ids"):
            gone.update(c["word_ids"])
        if c["reason"] == "manual":
            for w in transcript["words"]:  # a word mostly inside a manual cut is removed
                ov = min(w["end"], c["end"]) - max(w["start"], c["start"])
                if ov > 0.5 * (w["end"] - w["start"]):
                    gone.add(w["i"])
    return gone


def find_silences(transcript: dict, cuts: list[dict]) -> list[dict]:
    words = transcript["words"]
    gone = removed_words(transcript, cuts)
    kept = [w for w in words if w["i"] not in gone]
    out = []
    for a, b in zip(kept, kept[1:]):
        between_removed = any(a["i"] < k < b["i"] for k in gone)
        gap = b["start"] - a["end"]
        if not between_removed and gap > SILENCE_MAX:
            out.append({"reason": "silence", "start": round(a["end"] + PAD, 3), "end": round(b["start"] - PAD, 3),
                        "word_ids": [], "text": f"(lặng {gap:.2f}s)"})
    # audio-detected pauses (word timestamps often stretch over them); skip ones already covered
    taken = [(c["start"], c["end"]) for c in cuts + out]
    for s, e in transcript.get("silences", []):
        if e - s <= SILENCE_MAX or s <= words[0]["start"] or e >= words[-1]["end"]:
            continue
        cs, ce = s + PAD, e - PAD
        if any(ts <= cs + 0.05 and ce - 0.05 <= te for ts, te in taken):
            continue
        out.append({"reason": "silence", "start": round(cs, 3), "end": round(ce, 3), "word_ids": [],
                    "text": f"(lặng {e - s:.2f}s, audio)"})
    return out


def _snap_to_silence(t: float, silences: list[list[float]], side: str, pad: float) -> float:
    """Move a cut boundary into a real pause when one is close (prevents clipped syllables)."""
    for s, e in silences:
        if side == "start" and t - 0.35 <= e <= t + 0.25:
            return max(s, e - pad)
        if side == "end" and t - 0.25 <= s <= t + 0.35:
            return min(e, s + pad)
    return t


def compute_keep(transcript: dict, cuts: list[dict], pad: float = PAD) -> list[dict]:
    """Keep intervals in source time, snapped to the frame grid, never cutting inside a kept word."""
    words = transcript["words"]
    gone = removed_words(transcript, cuts)
    hard = [(c["start"], c["end"]) for c in cuts if c.get("enabled", True) and c["reason"] in ("silence", "manual")]
    runs: list[list[dict]] = []
    for w in words:
        if w["i"] in gone:
            continue
        if runs:
            prev = runs[-1][-1]
            if not any(prev["i"] < k < w["i"] for k in gone):
                runs[-1].append(w)
                continue
        runs.append([w])
    dur = transcript["duration"]
    keep = []
    for run in runs:
        first, last = run[0], run[-1]
        sil = transcript.get("silences", [])
        lo = _snap_to_silence(first["start"] - pad, sil, "start", pad)
        hi = _snap_to_silence(last["end"] + pad, sil, "end", pad)
        # never pull audio of an adjacent removed word into the keep
        prev_removed = [words[k]["end"] for k in gone if k < first["i"]]
        next_removed = [words[k]["start"] for k in gone if k > last["i"]]
        if prev_removed:
            lo = max(lo, max(prev_removed), first["start"] - pad)
            lo = min(lo, first["start"] - 0.02)
        if next_removed:
            hi = min(hi, min(next_removed))
            hi = max(hi, last["end"] + 0.02)
        lo, hi = max(0.0, lo), min(dur, hi)
        # floor start / ceil end to frames so we only ever grow the kept region
        lo_f = snap(lo) if snap(lo) <= lo else snap(lo - 1 / 30)
        hi_f = snap(hi) if snap(hi) >= hi else snap(hi + 1 / 30)
        keep.append({"start": max(0.0, lo_f), "end": min(dur, hi_f)})
    # subtract silence / manual cuts (they may sit inside a smeared word run)
    for s, e in hard:
        s_f, e_f = snap(s), snap(e)
        if e_f - s_f < 0.1:
            continue
        nxt = []
        for k in keep:
            if e_f <= k["start"] or s_f >= k["end"]:
                nxt.append(k)
                continue
            if k["start"] < s_f:
                nxt.append({"start": k["start"], "end": s_f})
            if e_f < k["end"]:
                nxt.append({"start": e_f, "end": k["end"]})
        keep = nxt
    merged: list[dict] = []
    for k in keep:
        if merged and k["start"] <= merged[-1]["end"] + 0.04:
            merged[-1]["end"] = max(merged[-1]["end"], k["end"])
        else:
            merged.append(dict(k))
    return [{"start": round(k["start"], 4), "end": round(k["end"], 4)} for k in merged]


def build_cut_list(transcript: dict) -> dict:
    retakes = find_retakes(transcript)
    taken = {k for c in retakes for k in c["word_ids"]}
    cuts = retakes + find_fillers(transcript, taken)
    cuts += find_silences(transcript, cuts)
    # leading / trailing dead air is handled by compute_keep (first/last word +- pad)
    cuts.sort(key=lambda c: c["start"])
    for n, c in enumerate(cuts, 1):
        c["id"] = f"c{n}"
        c["enabled"] = True
        c["start"], c["end"] = round(c["start"], 3), round(c["end"], 3)
    cuts = [{k: c[k] for k in ("id", "start", "end", "reason", "text", "enabled", "word_ids",
                                "similar_to", "kept_text", "similarity") if k in c} for c in cuts]
    keep = compute_keep(transcript, cuts)
    after = sum(k["end"] - k["start"] for k in keep)
    return {
        "source": transcript["source"],
        "approved": False,
        "pad": PAD,
        "afade_ms": AFADE_MS,
        "cuts": cuts,
        "keep": keep,
        "stats": {"original": transcript["duration"], "after": round(after, 2),
                  "removed": round(transcript["duration"] - after, 2), "n_cuts": len(cuts)},
    }
