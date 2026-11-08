# auto-edit-short

CLI tự động edit video short 9:16 (talking-head, tiếng Việt) bằng **Python + FFmpeg + HyperFrames**,
với Claude Code làm "nhạc trưởng": đọc transcript, ra quyết định và ghi file JSON; công cụ chuyên dụng làm phần nặng.

```
raw.mp4 → transcript.json → cut_list.json → edit_plan.json → final.mp4
```

| Bước | Việc | Công cụ |
|---|---|---|
| 1. Cắt | Transcribe từng từ, sửa glossary, đánh dấu từ đệm / take lặp / khoảng lặng → `cut_list.json` (duyệt) → cắt, fade 30 ms, đệm 0.15 s | mlx-whisper large-v3-turbo (hoặc PhoWhisper), FFmpeg silencedetect |
| 2. Đạo diễn | Claude viết `edit_plan.json`: scene normal / split / fullscreen, head text, zoom, logo, motion graphic | Claude Code |
| 3. Dựng | Tách người khỏi nền, nền studio, head text sau đầu, MG, caption 3 từ tô vàng, chuyển cảnh | Robust Video Matting, HyperFrames, GSAP |
| 4. Render + QA | 1080×1920 H.264 + AAC, loudnorm -14 LUFS, tự kiểm tra cụt chữ / caption bị che / định dạng | HyperFrames, FFmpeg |

Mẫu: [`samples/short12.mp4`](samples/short12.mp4) (đầu vào, bản 1080p) → [`output/short12_final.mp4`](output/short12_final.mp4) (kết quả).
Các file JSON trung gian của mẫu nằm ở [`work/short12/`](work/short12/).

## Cài đặt (macOS Apple Silicon)

```bash
brew install ffmpeg node
./scripts/setup.sh
source .venv/bin/activate
```

## Dùng

```bash
python -m autoedit transcribe samples/short12.mp4   # hoặc input/<ten>.mp4
python -m autoedit cutlist short12                  # duyệt work/short12/cut_list.json, đặt "approved": true
python -m autoedit cut short12
# Claude Code đọc work/short12/transcript.cut.json và viết work/short12/edit_plan.json (xem CLAUDE.md)
python -m autoedit build short12                    # plan-check → matte → compose → render → qa
```

Kết quả: `output/<ten>_final.mp4`, báo cáo QA và contact sheet ở `work/<ten>/qa/`.
Schema JSON, quy tắc dựng và cách viết edit plan: **[CLAUDE.md](CLAUDE.md)**.

## Tuỳ chỉnh

- `config/glossary.json` — từ hay bị nghe sai → từ đúng, danh sách từ đệm.
- `config/style.json` — font, màu, vị trí caption, độ kéo xuống của cảnh split, cỡ head text.
- `media/backgrounds/`, `media/logos/` — ảnh nền và logo chính thức.

## Nguồn và giấy phép bên thứ ba

- **Be Vietnam Pro** — SIL Open Font License 1.1 (`media/fonts/OFL.txt`).
- **Robust Video Matting** — GPL-3.0; model được tải về bởi `scripts/setup.sh`, không đi kèm repo.
- **Ảnh nền** — "El Caster Studio tv.jpg", Wikimedia Commons, CC0 (`media/backgrounds/SOURCES.md`).
- **Logo** — simple-icons (CC0) và Wikimedia Commons; tên và logo là nhãn hiệu của chủ sở hữu tương ứng.
- **HyperFrames**, **mlx-whisper**, **FFmpeg** — theo giấy phép của từng dự án.
