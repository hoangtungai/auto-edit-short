"""Step 1a: audio extraction + word-level Vietnamese transcription + glossary fix."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from .common import CONFIG, ROOT, detect_silences, extract_audio, ffprobe_duration, load, norm, save

MLX_MODEL = "mlx-community/whisper-large-v3-turbo"
PHO_MODEL = "vinai/PhoWhisper-small"

# Fillers that are also real Vietnamese particles: only count them when isolated by a pause.
AMBIGUOUS_FILLERS = {"à", "ạ", "ơ", "ừ", "ờ"}


def _glossary() -> dict:
    p = CONFIG / "glossary.json"
    return load(p) if p.exists() else {"replace": {}, "fillers": [], "prompt_terms": []}


# --------------------------------------------------------------------------- engines
def _run_mlx(wav: Path, prompt: str) -> list[dict]:
    import mlx_whisper

    r = mlx_whisper.transcribe(
        str(wav),
        path_or_hf_repo=MLX_MODEL,
        language="vi",
        task="transcribe",
        word_timestamps=True,
        initial_prompt=prompt,
        condition_on_previous_text=False,
        temperature=0.0,
    )
    out = []
    for seg in r["segments"]:
        for w in seg.get("words", []):
            out.append({"text": w["word"], "start": float(w["start"]), "end": float(w["end"])})
    return out


def _run_pho(wav: Path, prompt: str) -> list[dict]:
    import soundfile as sf
    import torch
    from transformers import pipeline

    p = pipeline("automatic-speech-recognition", model=PHO_MODEL, device="cpu", torch_dtype=torch.float32)
    a, sr = sf.read(str(wav))
    r = p({"raw": a.astype("float32"), "sampling_rate": sr}, return_timestamps="word", chunk_length_s=30,
          generate_kwargs={"language": "vi", "task": "transcribe"})
    return [{"text": " " + c["text"].strip(), "start": float(c["timestamp"][0]),
             "end": float(c["timestamp"][1] or c["timestamp"][0] + 0.2)} for c in r["chunks"]]


# --------------------------------------------------------------------------- post-processing
def _merge_tokens(raw: list[dict]) -> list[dict]:
    """Whisper marks a new word with a leading space; glue the rest ('90' + '%')."""
    words: list[dict] = []
    for t in raw:
        txt = unicodedata.normalize("NFC", t["text"])
        if not txt.strip():
            continue
        if words and not txt.startswith(" "):
            words[-1]["text"] += txt.strip()
            words[-1]["end"] = t["end"]
        else:
            words.append({"text": txt.strip(), "start": t["start"], "end": t["end"]})
    # strip pure-punctuation words into previous word
    out: list[dict] = []
    for w in words:
        if out and not norm(w["text"]):
            out[-1]["text"] += w["text"]
            continue
        out.append(w)
    for w in out:
        w["start"], w["end"] = round(w["start"], 3), round(max(w["end"], w["start"] + 0.04), 3)
    return out


def apply_glossary(words: list[dict], gl: dict) -> list[dict]:
    rules = sorted(((norm(k).split(), v) for k, v in gl.get("replace", {}).items()), key=lambda r: -len(r[0]))
    out, i = [], 0
    keys = [norm(w["text"]) for w in words]
    while i < len(words):
        hit = None
        for pat, rep in rules:
            n = len(pat)
            if n and keys[i:i + n] == pat:
                hit = (n, rep)
                break
        if hit:
            n, rep = hit
            last = words[i + n - 1]
            trail = re.search(r"[^\w%]+$", last["text"])
            out.append({"text": rep + (trail.group(0) if trail else ""), "start": words[i]["start"],
                        "end": last["end"], "raw": " ".join(w["text"] for w in words[i:i + n]), "fixed": True})
            i += n
        else:
            out.append({**words[i], "raw": words[i]["text"], "fixed": False})
            i += 1
    return out


def mark_fillers(words: list[dict], gl: dict) -> None:
    fillers = {norm(f) for f in gl.get("fillers", [])}
    for k, w in enumerate(words):
        key = norm(w["text"])
        is_f = key in fillers
        if is_f and key in AMBIGUOUS_FILLERS:
            gap_before = w["start"] - words[k - 1]["end"] if k else 1.0
            gap_after = words[k + 1]["start"] - w["end"] if k + 1 < len(words) else 1.0
            is_f = gap_before >= 0.12 or gap_after >= 0.12 or w["text"].endswith((",", "..."))
        w["filler"] = bool(is_f)


def build_segments(words: list[dict], gap: float = 0.35) -> list[dict]:
    segs, cur = [], []
    for k, w in enumerate(words):
        if cur and (w["start"] - words[k - 1]["end"] >= gap):
            segs.append(cur)
            cur = []
        cur.append(k)
        if re.search(r"[.?!…]$", w["text"]):
            segs.append(cur)
            cur = []
    if cur:
        segs.append(cur)
    return [{"id": i, "start": words[s[0]]["start"], "end": words[s[-1]]["end"],
             "text": " ".join(words[j]["text"] for j in s), "word_ids": s} for i, s in enumerate(segs)]


def drop_tail_hallucinations(words: list[dict], duration: float) -> list[dict]:
    """Whisper repeats lines / invents words past the end of the media."""
    return [w for w in words if w["start"] < duration - 0.05]


def _rel(p: Path) -> str:
    """Store project-relative paths so shared JSON never leaks the local home directory."""
    try:
        return str(Path(p).resolve().relative_to(ROOT))
    except ValueError:
        return Path(p).name


def transcribe(media: Path, out_json: Path, engine: str = "mlx") -> dict:
    media = Path(media)
    wav = out_json.parent / (out_json.stem + ".wav")
    extract_audio(media, wav)
    gl = _glossary()
    # Prompt nudges Whisper to keep disfluencies (needed to find fillers/retakes) and spell tool names.
    prompt = "Ừm, à, ờ... thì, ừm, mình nói lại nhé. " + ", ".join(gl.get("prompt_terms", [])) + "."
    raw = _run_mlx(wav, prompt) if engine == "mlx" else _run_pho(wav, prompt)
    duration = ffprobe_duration(media)
    words = drop_tail_hallucinations(_merge_tokens(raw), duration)
    words = apply_glossary(words, gl)
    mark_fillers(words, gl)
    for i, w in enumerate(words):
        w["i"] = i
    words = [{"i": w["i"], "text": w["text"], "start": w["start"], "end": w["end"], "raw": w["raw"],
              "fixed": w["fixed"], "filler": w["filler"]} for w in words]
    data = {
        "source": _rel(media),
        "duration": round(duration, 3),
        "language": "vi",
        "engine": MLX_MODEL if engine == "mlx" else PHO_MODEL,
        "words": words,
        "segments": build_segments(words),
        "silences": detect_silences(wav),
    }
    save(out_json, data)
    return data
