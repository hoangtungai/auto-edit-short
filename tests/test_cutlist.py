"""Synthetic checks for Step 1 decisions (run: .venv/bin/python -m pytest -q tests)."""
from autoedit.cutlist import build_cut_list, compute_keep
from autoedit.transcribe import apply_glossary, build_segments, mark_fillers

GL = {"replace": {"Cloud Code": "Claude Code"}, "fillers": ["ừm", "à", "ờ"]}


def make(spec):
    """spec: list of (text, start, end)."""
    words = [{"text": t, "start": s, "end": e} for t, s, e in spec]
    words = apply_glossary(words, GL)
    mark_fillers(words, GL)
    for i, w in enumerate(words):
        w["i"] = i
    return {"source": "x.mp4", "duration": spec[-1][2] + 1.0, "words": words,
            "segments": build_segments(words), "silences": []}


def test_glossary_ngram():
    t = make([("Mình", 0, .2), ("dùng", .2, .4), ("Cloud", .4, .6), ("Code.", .6, .9)])
    assert [w["text"] for w in t["words"]] == ["Mình", "dùng", "Claude Code."]
    assert t["words"][2]["fixed"] and t["words"][2]["start"] == .4 and t["words"][2]["end"] == .9


def test_filler_and_particle():
    # "ừm" isolated -> filler ; "à" glued inside a phrase -> not a filler
    t = make([("Hôm", 0, .2), ("nay", .2, .4), ("ừm", .7, 1.0), ("mình", 1.3, 1.5), ("nói", 1.5, 1.7),
              ("vậy", 1.7, 1.9), ("à", 1.9, 2.0), ("thật", 2.0, 2.2), ("hay.", 2.2, 2.5)])
    fl = [w["text"] for w in t["words"] if w["filler"]]
    assert fl == ["ừm"]
    cl = build_cut_list(t)
    assert [c["reason"] for c in cl["cuts"]] == ["filler"]


def test_retake_keeps_later_take():
    t = make([("Tại", 0, .2), ("sao", .2, .4), ("một", .4, .6), ("cái", .6, .8), ("app.", .8, 1.0),
              ("Tại", 1.6, 1.8), ("sao", 1.8, 2.0), ("một", 2.0, 2.2), ("cái", 2.2, 2.4), ("ứng", 2.4, 2.6),
              ("dụng", 2.6, 2.8), ("tiết", 2.8, 3.0), ("kiệm.", 3.0, 3.3)])
    cl = build_cut_list(t)
    r = [c for c in cl["cuts"] if c["reason"] == "retake"]
    assert len(r) == 1 and r[0]["word_ids"] == [0, 1, 2, 3, 4]
    keep = cl["keep"]
    assert keep[0]["start"] >= 1.0 and keep[0]["start"] <= 1.6 - 0.02  # starts in the gap before take 2
    assert keep[-1]["end"] >= 3.3 + 0.1                                   # tail padded, no clipped word


def test_long_silence_shortened_and_no_word_clipped():
    t = make([("Một", 0, .3), ("hai.", .3, .6), ("Ba", 2.6, 2.9), ("bốn.", 2.9, 3.2)])
    cl = build_cut_list(t)
    assert any(c["reason"] == "silence" for c in cl["cuts"])
    keep = compute_keep(t, cl["cuts"])
    assert len(keep) == 2
    for w in t["words"]:  # every kept word lies fully inside one keep interval
        assert any(k["start"] <= w["start"] and w["end"] <= k["end"] for k in keep)
    gap_out = keep[1]["start"] - keep[0]["end"]
    assert gap_out > 1.0  # removed most of the 2.0 s pause


def test_disabled_cut_is_respected():
    t = make([("Hôm", 0, .2), ("nay", .2, .4), ("ừm", .7, 1.0), ("mình", 1.3, 1.5), ("nói.", 1.5, 1.8)])
    cl = build_cut_list(t)
    cl["cuts"][0]["enabled"] = False
    assert len(compute_keep(t, cl["cuts"])) == 1
