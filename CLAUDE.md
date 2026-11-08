# auto-edit-short — CLI tự động edit video short 9:16 (talking-head)

Claude Code là **nhạc trưởng**: đọc transcript, ra quyết định, ghi file JSON.
Công cụ chuyên dụng làm phần nặng: FFmpeg (audio/cắt/mux/loudnorm), PhoWhisper (transcribe tiếng Việt),
Robust Video Matting (tách người), HyperFrames (dựng head text, motion graphic, caption, zoom, chuyển cảnh).

```
input/<name>.mp4 ──transcribe──▶ transcript.json ──cutlist──▶ cut_list.json (NGƯỜI DUYỆT)
   ──cut──▶ cut.mp4 + transcript.cut.json ──(Claude làm đạo diễn)──▶ edit_plan.json
   ──matte──▶ person.webm (alpha) ──compose──▶ hf/ (dự án HyperFrames) ──render──▶ output/<name>_final.mp4
   ──qa──▶ qa/ (khung hình kiểm tra + qa_report.json)
```

## Chạy

```bash
source .venv/bin/activate          # Python 3.14 venv: torch, transformers, mlx-whisper, opencv
python -m autoedit transcribe samples/short12.mp4    # B1: audio + transcript.json (đã sửa glossary)
python -m autoedit cutlist short12                   # B1: cut_list.json -> DỪNG cho người duyệt
python -m autoedit cut short12                       # B1: chỉ chạy khi cut_list.approved == true
python -m autoedit plan-check short12                # B2: validate edit_plan.json + thống kê tỉ lệ cảnh
python -m autoedit matte short12                     # B3: RVM -> person.webm
python -m autoedit compose short12                   # B3: sinh dự án HyperFrames từ edit_plan.json
python -m autoedit render short12                    # B4: render + loudnorm -14 LUFS
python -m autoedit qa short12                        # B4: chụp khung hình ở điểm cắt, kiểm tra
python -m autoedit build short12                     # B2→B4 một lèo (sau khi đã có edit_plan.json)
```

HyperFrames CLI được cài cục bộ (`package.json`, `hyperframes@0.9.23`). `~/.npm` của máy này thuộc root nên
luôn dùng `npm_config_cache=$PWD/.npm-cache` (code Python đã tự đặt biến này).

Mọi file trung gian nằm ở `work/<name>/`. Kết quả cuối ở `output/<name>_final.mp4`.

## Cấu trúc thư mục

```
autoedit/            package Python (mỗi bước một module)
config/glossary.json từ hay bị nghe sai -> từ đúng
config/style.json    font, màu, vị trí caption, thông số layout
media/logos/         logo CHÍNH THỨC (tải từ nguồn chính chủ / simple-icons / Wikimedia). KHÔNG tự vẽ.
media/backgrounds/   ảnh nền studio (tải trên mạng, ghi nguồn trong media/backgrounds/SOURCES.md)
media/fonts/         Be Vietnam Pro (OFL, Google Fonts) — đủ dấu tiếng Việt
templates/           template scene HyperFrames (motion graphic, caption, head text...)
input/  output/  work/
```

---

## Schema các file JSON

Thời gian luôn tính bằng **giây (float)**. Toạ độ theo canvas **1080×1920**.

### transcript.json (`work/<name>/transcript.json`, sau cắt: `transcript.cut.json`)

```json
{
  "source": "input/short12.mp4",
  "duration": 41.1,
  "language": "vi",
  "engine": "mlx-community/whisper-large-v3-turbo",
  "silences": [[10.19, 10.46], [15.27, 15.63]],
  "words": [
    {"i": 0, "text": "Hôm", "start": 0.32, "end": 0.51, "raw": "hôm", "fixed": false, "filler": false}
  ],
  "segments": [
    {"id": 0, "start": 0.32, "end": 3.1, "text": "Hôm nay mình ...", "word_ids": [0, 1, 2]}
  ]
}
```
- `raw`: chữ gốc model trả về; `fixed: true` khi bị glossary sửa; `filler: true` nếu là từ đệm.
- `segments`: câu/cụm, tách theo dấu câu hoặc khoảng lặng ≥ 0.35 s.

### config/glossary.json

```json
{
  "replace": {"Cloud Code": "Claude Code", "clo code": "Claude Code"},
  "fillers": ["ừm", "ừ", "à", "ờ", "ơ", "hừm", "um", "uh"]
}
```
- Khớp không phân biệt hoa/thường, khớp theo **cụm từ liên tiếp** (n-gram), thay cả cụm thành chữ đúng
  (giữ timestamp: start của từ đầu, end của từ cuối).

### cut_list.json (`work/<name>/cut_list.json`)

```json
{
  "source": "input/short12.mp4",
  "approved": false,
  "pad": 0.15,
  "afade_ms": 30,
  "cuts": [
    {"id": "c1", "start": 3.42, "end": 3.80, "reason": "filler", "text": "ừm", "enabled": true},
    {"id": "c2", "start": 5.10, "end": 9.02, "reason": "retake", "text": "câu nói hỏng...",
     "similar_to": "s4", "similarity": 0.83, "enabled": true}
  ],
  "keep": [{"start": 0.0, "end": 3.42}],
  "stats": {"original": 41.1, "after": 35.2, "removed": 5.9}
}
```
- `reason`: `filler` | `retake` | `silence` (khoảng lặng > 0.8 s rút về 0.3 s) | `manual`.
- Người duyệt: sửa `enabled` / thêm cut `manual`, rồi đặt `"approved": true`. `cut` **từ chối chạy** nếu chưa approved.

### edit_plan.json (`work/<name>/edit_plan.json`) — Claude viết

```json
{
  "source": "work/short12/cut.mp4",
  "duration": 35.2,
  "background": "media/backgrounds/studio_01.jpg",
  "events": [
    {"t": 0.0,  "type": "scene",     "params": {"layout": "normal", "dur": 4.2, "transition": "none"}},
    {"t": 0.1,  "type": "head_text", "params": {"text": "CLAUDE CODE", "sub": "làm editor cho bạn", "dur": 4.0}},
    {"t": 1.8,  "type": "zoom",      "params": {"to": 1.12, "dur": 0.5, "hold": 1.6, "ease": "power2.out"}},
    {"t": 4.2,  "type": "scene",     "params": {"layout": "split", "dur": 6.0, "transition": "slide-up",
                 "mg": {"template": "steps", "title": "3 bước", "items": ["Cắt", "Dựng", "Render"]}}},
    {"t": 5.0,  "type": "logo",      "params": {"name": "claude", "file": "media/logos/claude.svg", "dur": 2.5}},
    {"t": 10.2, "type": "scene",     "params": {"layout": "fullscreen", "dur": 5.0, "transition": "zoom-blur",
                 "mg": {"template": "stat", "value": "10x", "label": "nhanh hơn edit tay"}}}
  ]
}
```

`type` và `params`:

| type | params | ghi chú |
|---|---|---|
| `scene` | `layout` (`normal`/`split`/`fullscreen`), `dur`, `transition`, `mg` (bắt buộc với split/fullscreen) | Các `scene` phải phủ kín [0, duration], không chồng nhau |
| `head_text` | `text` (≤ 3 từ, IN HOA), `sub` (tùy chọn), `dur` | Chỉ trong scene `normal`; luôn nằm **sau đầu nhân vật** |
| `zoom` | `to` (1.0–1.25), `dur` (thời gian chuyển), `hold`, `ease` | Zoom wrapper chứa nền + head text + người cùng lúc |
| `logo` | `name`, `file` (trong media/logos), `dur`, `pos` (`top-left`/`top-right`/`beside-head`) | Hiện khi transcript nhắc tới công cụ |
| `sfx` | `name`, `gain` | tùy chọn, whoosh khi chuyển cảnh |

`transition`: `none` | `fade` | `slide-up` | `slide-left` | `zoom-blur` | `wipe` | `push`. Dài 0.35–0.5 s.

`mg.template` (motion graphic dựng sẵn, tham số hoá; `at` = thời điểm tuyệt đối phần tử xuất hiện, khớp lúc nói):
- `list` / `steps` {title, items:[{text, logo?, at}] (≤4)} — steps tự đánh số, mục cuối có dấu ✓
- `flow` {title, nodes:[{label, sub, logos?:[...], at}] (≤4)} — sơ đồ dọc có mũi tên (hợp fullscreen)
- `strike` {kicker, title (1 dòng), stamp, strike_at, sub, sub_at} — gạch bỏ + con dấu
- `title` {title, sub} · `stat` {value, label}
`head_text.params.accent`: danh sách từ tô vàng. `sub` là dòng kicker nằm **phía trên** dòng chính → viết sao cho đọc
từ trên xuống thành câu (vd. sub "APP EDIT VIDEO GIÚP" + text "TIẾT KIỆM 90%").
Chữ trong motion graphic phải **giải thích đúng nội dung đang nói** trong khoảng thời gian của scene.

---

## Quy tắc

### Bước 1 — Cắt và bỏ take hỏng
- FFmpeg tách audio mono 16 kHz. Transcribe tiếng Việt mặc định bằng **mlx-whisper large-v3-turbo**
  (`--engine mlx`, GPU Apple, ~12 s cho 41 s audio, word timestamps). **PhoWhisper** dùng qua `--engine pho`
  (`vinai/PhoWhisper-small`, CPU). Lý do: trên máy M2 8 GB, PhoWhisper-medium crash ở MPS và swap nặng ở CPU.
  `initial_prompt` gồm từ đệm + `prompt_terms` trong glossary để Whisper giữ disfluency và viết đúng tên công cụ.
- Timestamp từ của Whisper hay "phủ" lên chỗ ngừng → luôn chạy thêm `silencedetect` (-35 dB, ≥0.2 s), lưu ở
  `transcript.silences`; khoảng lặng > 0.8 s bị rút ngắn, và điểm cắt được **neo vào chỗ lặng thật** nếu có gần đó.
- Sửa theo `config/glossary.json` trước khi phân tích.
- Đánh dấu từ đệm (ừm, à, ờ…). Câu lặp (similarity ≥ 0.70, rapidfuzz `token_set_ratio` trên câu đã chuẩn hoá)
  → **giữ take sau**, cắt take trước (và phần dở dang giữa hai take).
- Ghi `cut_list.json`, **dừng cho người duyệt**.
- Khi cắt: đệm 0.15 s mỗi đầu đoạn giữ (không cắt vào chữ), audio fade 30 ms mỗi mối nối, không cụt chữ
  (điểm cắt không được nằm trong [start, end] của một từ được giữ). Sau khi cắt **transcribe lại** → `transcript.cut.json`.

### Bước 2 — Đạo diễn (Claude viết edit_plan.json)
- Nhịp: **2–3 giây một thay đổi hình ảnh** (zoom, logo, head text, chuyển scene, MG đổi nội dung).
- **20–30% tổng thời lượng là scene `fullscreen`**: motion graphic thay toàn bộ màn hình (audio vẫn chạy),
  giải thích nội dung đang nói.
- **20–30% tổng thời lượng là scene `split`**: nhân vật kéo xuống **1/6 chiều cao (320 px)**; motion graphic
  nằm ở vùng trên đầu nhân vật; **caption đặt ở 50% chiều cao (y = 960)**, ngay trên đầu nhân vật.
- Phần còn lại là `normal`: nhân vật ở vị trí gốc (khoảng trống 1/3 trên đầu), head text sau đầu, zoom, logo.
- Giữa các scene **luôn có chuyển cảnh** (không cắt cứng giữa các layout khác nhau).
- Hook trong 1 giây đầu: scene đầu là `normal` + head_text ngay từ t≈0.1.
- Logo: bản chính thức lưu trong `media/logos/<name>.svg|png`. Không tự vẽ logo.
- Chạy `python -m autoedit plan-check <name>` — phải pass (phủ kín, tỉ lệ 20–30%, nhịp ≤ 3 s).

### Bước 3 — Dựng hình
- Tách người bằng **Robust Video Matting** (TorchScript mobilenetv3, MPS, ~mấy phút cho 41 s) → `person.webm`
  VP9 có alpha 1080×1920 + `head_track.json` (đỉnh đầu / tâm đầu từng frame) dùng để đặt head text, caption và QA.
- Mỗi scene split/fullscreen là một sub-composition `hf/compositions/mgN.html`; caption ở `captions.html`;
  `layout.json` ghi lại toạ độ thực tế (caption box, head text, vùng MG) cho bước QA.
- Thứ tự lớp (z-index, dưới → trên): ảnh nền studio → head text → người (cutout) → logo → motion graphic → caption.
- Nền: ảnh studio trong `media/backgrounds/` (đã crop 9:16 + blur bằng FFmpeg, nguồn ghi ở `SOURCES.md`),
  Ken Burns nhẹ 1.00→1.06.
- **Font: Be Vietnam Pro** (Black 900 cho head text, ExtraBold 800 cho caption) — đủ dấu tiếng Việt.
- Head text: chữ to, nằm sau đầu (che 30–55% bởi đầu), **đổ bóng** (`text-shadow` nhiều lớp),
  **fade in** (opacity + y + blur 0.5 s, power3.out) và **fade out** (0.4 s, power2.in).
- Caption: từng từ, **nhóm 3 từ**, từ đang nói tô **vàng #FFD60A**, chữ trắng viền/bóng đen, fade in/out mỗi nhóm.
  Vị trí: scene normal tâm y = 1330 (ngực, dưới mặt), fullscreen tâm y = 1560.
  Scene split: caption đặt **ở 50% chiều cao (y = 960) nhưng không bao giờ đè lên đầu** — đáy caption =
  min(960 + h/2, đỉnh đầu thật (đo từ matte) + 320 − 18). Với short12 đỉnh đầu ở y≈536 nên caption nằm ≈ y 790.
- Head text: cỡ chữ tính bằng PIL theo font thật, chia cho mức zoom lớn nhất trong lúc hiển thị (không tràn khi zoom).
  Đường baseline = đỉnh đầu + 35% chiều cao chữ hoa → đầu che phần dưới chữ ở giữa khung.
- Zoom bằng GSAP transform trên wrapper. Chuyển cảnh bằng GSAP (clip-path / transform / blur trên lớp con).

### Bước 4 — Render và tự kiểm tra
- HyperFrames render 1080×1920 30 fps → FFmpeg mux audio của `cut.mp4`, `loudnorm=I=-14:TP=-1.5:LRA=11`
  (2 pass), H.264 (`libx264 -crf 18 -pix_fmt yuv420p`) + AAC 192k, `+faststart`.
- `qa`: chụp khung hình tại mỗi điểm cắt (±0.2 s) và giữa mỗi scene; kiểm tra:
  cụt chữ (khoảng cách điểm cắt tới từ gần nhất ≥ 0.1 s), caption bị che (caption không đè mặt/MG, nằm trong 80% title-safe),
  loudness -14 ± 1 LUFS, kích thước/codec đúng. Sai thì sửa plan/style rồi render lại.

## Quy ước làm việc
- Làm lần lượt từng bước; xong mỗi bước chạy thử trên `samples/short12.mp4` và cho người dùng xem kết quả trước khi sang bước sau.
- Không ghi đè input. Không commit `.venv/`, model weights, video gốc trong `input/` (>100 MB); chỉ commit JSON của `work/short12/` và `output/short12_final.mp4` làm mẫu. JSON chỉ chứa đường dẫn tương đối.
