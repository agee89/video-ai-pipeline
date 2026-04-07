# Video AI Pipeline

Auto-clipping YouTube videos dengan face tracking, active speaker detection, auto-caption, dan **Streamlit Dashboard**.

## Directory Structure

```
video-ai-pipeline/
├── docker-compose.yml       # Docker orchestration
├── .env                     # Environment variables
├── Readme.md                # This file
├── CLAUDE.md                # AI assistant context
├── storage/output/          # Local output storage
├── dashboard/               # Streamlit UI
│   ├── Dockerfile
│   ├── app.py               # Main application
│   └── requirements.txt
├── video-api/
│   ├── Dockerfile
│   ├── main.py              # FastAPI endpoints
│   └── requirements.txt
└── video-worker/
    ├── Dockerfile
    ├── worker.py            # Job processor
    ├── requirements.txt
    ├── fonts/               # Custom fonts (.ttf)
    │   ├── README.md
    │   ├── KOMIKAX_.ttf
    │   └── theboldfont.ttf
    └── modules/
        ├── fetcher.py       # YouTube download + partial download
        ├── portrait.py      # Face tracking + active speaker
        ├── captioner.py     # Whisper + ASS subtitles
        ├── cutter.py        # Video segment cutting
        ├── exporter.py      # MinIO upload
        ├── callback.py      # Webhook notifications
        ├── thumbnail.py     # Thumbnail generator
        ├── video_source.py  # Video source overlay
        ├── image_watermark.py # Image watermark overlay
        ├── video_merge.py   # Video concatenation
        └── image_to_video.py # Image to video converter
```

---

## Configuration (.env)

Pastikan file `.env` tersedia di root folder dengan isi berikut:

```ini
S3_BUCKET_NAME=video-clips
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
REDIS_URL=redis://redis:6379
STORAGE_ENDPOINT=http://minio:9000
N8N_WEBHOOK_URL=https://local.yourdomain.my.id/webhook/clipper-generator
```

### Penjelasan Variable

| Variable | Deskripsi | Context |
|----------|-----------|---------|
| `S3_BUCKET_NAME` | Nama bucket penyimpanan video/clip | MinIO |
| `S3_ACCESS_KEY` | Username/Access Key Object Storage | MinIO |
| `S3_SECRET_KEY` | Password/Secret Key Object Storage | MinIO |
| `REDIS_URL` | URL koneksi ke Redis service | Job Queue |
| `STORAGE_ENDPOINT`| Internal Service URL untuk MinIO | Backend |
| `N8N_WEBHOOK_URL` | Endpoint Webhook untuk submit job dari Dashboard | Integration |

---

## Quick Start

```bash
# Start services
docker-compose up -d

# Monitor logs
docker logs video_worker -f

# Access Dashboard
http://localhost:8501


docker logs video_dashboard -f
```

---

## 1. Video Clipping

```bash
curl -X POST http://host.docker.internal:8000/process_video \
  -H "Content-Type: application/json" \
  -d '{
    "youtube_url": "https://www.youtube.com/watch?v=VIDEO_ID",
    "start_time": "2:30",
    "end_time": "3:00",
    "portrait": true,
    "face_tracking": true,
    "tracking_sensitivity": 8,
    "clip_number": 1,
    "channel_name": "My Channel",
    "callback_url": "http://optional-webhook-url"
  }'
```

### Video Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `youtube_url` | string | required | YouTube URL |
| `start_time` | string | required | Format: `mm:ss` or `hh:mm:ss` |
| `end_time` | string | required | Format: `mm:ss` or `hh:mm:ss` |
| `portrait` | bool | false | Convert to 9:16 portrait |
| `face_tracking` | bool | false | Enable active speaker tracking |
| `clip_number` | int | null | Passthrough ID for tracking |
| `channel_name` | string | null | Passthrough Channel Name |
| `tracking_sensitivity` | int | 5 | 1-10 (1=stay longer, 10=switch faster) |
| `camera_smoothing` | float | 0.25 | 0.05-0.5 (higher = faster camera movement) |
| `zoom_threshold` | float | 20.0 | 5.0-30.0 (Lip activity threshold: higher = less sensitive) |
| `zoom_level` | float | 1.15 | 1.0-1.5 (Target zoom factor: 1.15 = 15% zoom) |
| `split_screen` | bool | false | **Dynamic Stack Layout** (2-Person Split Screen) |
| `split_threshold` | float | 0.5 | 0.0-1.0 (Threshold to trigger split mode) |
| `callback_url` | string | null | Optional webhook URL for job completion |

### Face Tracking Parameters Guide

#### How Face Tracking Works

1. **Initial Scan**: Sistem scan seluruh video untuk memetakan wajah dan mendeteksi perubahan scene (*Two-Pass Analysis*)
2. **Global Timeline Stabilization**: Analisa timeline secara global untuk mengisi gap kecil (<1s) dan membuang noise singkat (<2s)
3. **Dual Lip Activity Trigger**: Split Screen hanya aktif jika **KEDUA** orang terdeteksi bicara/tertawa (bukan hanya deteksi wajah)
4. **Scene Cut Detection**: Kamera otomatis "snap" saat adegan berganti (anti-swipe effect)
5. **Stabilized Lock**: Kamera stabil dengan logika "Anchor", tidak bergetar mengikuti noise deteksi
6. **Smart Dominance Check**: Mencegah split jika satu orang sangat dominan
7. **Dynamic Zoom**: Otomatis zoom-in (customizable) saat tertawa/terkejut/speaking aktif
8. **Full HD Output**: Output otomatis di-upscale ke 1080x1920 (High Quality Portrait)

> Dokumentasi teknis lengkap: [FACE_TRACKING.md](./FACE_TRACKING.md)

#### `tracking_sensitivity` (1-10)

Mengontrol seberapa cepat kamera **berpindah antar orang** dan berapa lama harus menunggu.

| Value | Sustained Time | Cooldown | Mode | Best For |
|-------|---------------|----------|------|----------|
| 1-3 | 2.5-3.0s | 1.5-2.0s | Normal | 1 speaker, interview |
| 4-6 | 1.5-2.0s | 1.0-1.5s | Normal | Podcast 2 orang |
| 7-8 | 1.0-1.5s | 0.7-1.0s | **Dialog Mode** | Dialog 2 orang dinamis |
| 9-10 | 0.5-1.0s | 0.5-0.7s | **Dialog Mode** | Talk show responsif |

**Dialog Mode (sensitivity ≥7 + 2 orang):**
- Switch jika orang lain **2x lebih aktif**
- Minimum stay **2.5 detik** setelah switch
- Tidak "ragu-ragu" bolak-balik

#### `camera_smoothing` (0.05-0.5)

Mengontrol **kecepatan pergerakan kamera** saat mengikuti wajah.

| Value | Speed | Effect |
|-------|-------|--------|
| 0.05 | Sangat lambat | Sinematik, smooth, cocok untuk konten formal |
| 0.15 | Lambat | Transisi halus |
| 0.25 | Medium (default) | Balance antara smooth dan responsif |
| 0.35 | Cepat | Tracking lebih ketat |
| 0.50 | Instant | Mengikuti wajah tanpa delay |

#### `zoom_threshold` & `zoom_level`

Mengontrol perilaku Dynamic Zoom.

*   **`zoom_threshold` (Default 20.0)**:
    *   Angka Tinggi (>20): Hanya zoom saat tertawa lebar / kaget.
    *   Angka Rendah (<10): Zoom saat bicara biasa.
*   **`zoom_level` (Default 1.15)**:
    *   1.0: Zoom mati.
    *   1.15: Zoom 15% (subtle).
    *   1.50: Zoom 50% (extreme close-up).

#### `split_screen` & `split_threshold`

Mode **Dynamic Stack** mirip dengan gaya video podcast viral/wawancara.

*   **`split_screen` (Default: false)**:
    *   Jika `true`, sistem akan melacak **2 Wajah** sekaligus dengan metode **Global Analysis**.
    *   **Logic**: Split hanya aktif jika `LipActivity(Person1) > Threshold` **DAN** `LipActivity(Person2) > Threshold` (Keduanya Bicara/Tertawa).
    *   **Anti-Jitter**: Menerapkan stabilisasi global untuk mencegah "flicker" atau potong-potong cepat.
*   **`split_threshold` (Default: 0.5)**:
    *   Sekarang lebih relevan ke **Lip Sensitivity**.
    *   Lower (0.3) = Lebih sensitif terhadap gerakan bibir kecil.
    *   Higher (0.8) = Hanya split saat tertawa lebar/teriak bareng.

#### Rekomendasi Kombinasi

| Skenario | sensitivity | smoothing | Catatan |
|----------|-------------|-----------|---------|
| Interview 1 orang | 3 | 0.15 | Fokus stabil, lock mode aktif |
| Podcast 2 orang | 7 | 0.25 | Dialog mode, switch cepat |
| Talk show / panel | 5 | 0.20 | Balanced untuk 3+ orang |
| Dialog dinamis | 9 | 0.30 | Responsif 2-person |
| Wide shot grup | 3 | 0.20 | Prioritas aktivitas |

```json
// Contoh payload lengkap
{
  "youtube_url": "https://youtube.com/watch?v=VIDEO_ID",
  "start_time": "1:30",
  "end_time": "3:00",
  "portrait": true,
  "face_tracking": true,
  "tracking_sensitivity": 5,
  "camera_smoothing": 0.15,
  "zoom_threshold": 20.0,
  "zoom_level": 1.15,
  "split_screen": true,
  "split_threshold": 0.5
}
```

---

## 2. Auto Caption

```bash
curl -X POST http://host.docker.internal:8000/add_captions \
  -H "Content-Type: application/json" \
  -d '{
    "video_url": "http://minio-video:9002/video-clips/job_xxx.mp4",
    "language": "id",
    "model": "medium",
    "settings": {
      "font_family": "Montserrat",
      "font_size": 60,
      "line_color": "#FFFFFF",
      "word_color": "#FFDD5C",
      "all_caps": true,
      "max_words_per_line": 3,
      "bold": true,
      "outline_width": 3,
      "margin_v": 640,
      "position": "bottom_center"
    }
  }'
```

### Caption Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `video_url` | string | required | Video URL (S3/HTTP) |
| `language` | string | "id" | Whisper Language Code |
| `model` | string | "medium" | Whisper Model Size |
| `capt_number` | int | null | Passthrough ID |
| `settings` | object | {} | Custom Styling |
| `callback_url` | string | null | Optional. If set, runs async. |

### Supported Settings (within `settings` object)

| Name | Default | Description |
|------|---------|-------------|
| `font_family` | "Montserrat" | Font name (matches file if installed, e.g. "Komika Axis") |
| `font_size` | 60 | Font size in pixels |
| `line_color` | "#FFFFFF" | Main text color (Hex) |
| `word_color` | "#FFDD5C" | Highlight color for current word (Hex) |
| `outline_color` | "#000000" | Outline/Stroke color (Hex) |
| `outline_width` | 3 | Width of text outline in pixels |
| `bold` | true | Bold text style |
| `italic` | false | Italic text style |
| `all_caps` | true | Force uppercase text |
| `max_words_per_line` | 3 | Maximum words per line |
| `margin_v` | 640 | Vertical margin from bottom edge (px) |
| `position` | "bottom_center" | Anchor position (e.g. `top_left`, `center`, `bottom_center`) |

### Example Payload
```json
{
  "video_url": "http://minio-nca:9000/video-clips/input.mp4",
  "language": "id",
  "model": "small",
  "settings": {
    "font_family": "Komika Axis",
    "font_size": 55,
    "line_color": "#FFFFFF",
    "word_color": "#00FF00",
    "outline_color": "#FF0000",
    "outline_width": 10,
    "bold": true,
    "italic": false,
    "all_caps": true,
    "margin_v": 200,
    "position": "bottom_center"
  }
}
```

### Whisper Models

| Model | Size | RAM | Quality | Speed |
|-------|------|-----|---------|-------|
| `tiny` | 39 MB | ~1 GB | Basic | Fastest |
| `base` | 74 MB | ~1 GB | Good | Fast |
| `small` | 244 MB | ~2 GB | Better | Medium |
| `medium` | 769 MB | ~5 GB | Best for ID | Slow |
| `large` | 1.5 GB | ~10 GB | Best | Slowest |

### Response Example (Synchronous)

```json
[
  {
    "job_id": "caption_12345678",
    "capt_number": 1,
    "url_capt_video": "http://minio-storage:9002/video-clips/caption_12345678.mp4"
  }
]
```

---

## 3. Transcribe YouTube

Dapatkan transcript dari video YouTube dengan timestamps.

### Mode 1: YouTube Transcript (Default - CEPAT)

Mengambil subtitle langsung dari YouTube. Sangat cepat, tidak perlu download video.

```bash
curl -X POST http://host.docker.internal:8000/transcribe_youtube \
  -H "Content-Type: application/json" \
  -d '{
    "youtube_url": "https://www.youtube.com/watch?v=VIDEO_ID",
    "language": "id"
  }'
```

### Mode 2: Whisper AI (AKURAT)

Transcribe menggunakan Whisper AI. Lebih akurat, tapi lebih lambat.

```bash
curl -X POST http://host.docker.internal:8000/transcribe_youtube \
  -H "Content-Type: application/json" \
  -d '{
    "youtube_url": "https://www.youtube.com/watch?v=VIDEO_ID",
    "language": "id",
    "use_whisper": true,
    "model": "medium"
  }'
```

### Transcribe Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `youtube_url` | string | required | YouTube video URL |
| `language` | string | "id" | Language code |
| `use_whisper` | bool | false | false=YouTube (cepat), true=Whisper (akurat) |
| `model` | string | "medium" | Whisper model (hanya jika use_whisper=true) |
| `start_time` | string | null | Optional start (mm:ss) |
| `end_time` | string | null | Optional end (mm:ss) |

### Perbandingan Mode

| Mode | Kecepatan | Akurasi | Kebutuhan |
|------|-----------|---------|-----------|
| YouTube | ~5 detik | Baik | Video harus punya subtitle |
| Whisper | ~5 menit | Sangat baik | Download video + transcribe |

### Response

```json
{
  "job_id": "transcribe_abc123",
  "video_id": "VIDEO_ID",
  "language": "id",
  "source": "youtube",
  "transcript": {
    "text": "Teks lengkap transkrip...",
    "segments": [
      {
        "start": 0.0,
        "end": 3.5,
        "text": "Kalimat pertama"
      },
      {
        "start": 3.5,
        "end": 7.2,
        "text": "Kalimat kedua"
      }
    ]
  }
}
```

> **Note**: Jika YouTube transcript tidak tersedia, sistem akan otomatis fallback ke Whisper.

---

## 4. Thumbnail Generator

Generate thumbnail dari video dengan face detection dan text overlay.

```bash
curl -X POST http://host.docker.internal:8000/generate_thumbnail \
  -H "Content-Type: application/json" \
  -d '{
    "video_url": "http://minio-video:9002/video-clips/job_xxx.mp4",
    "size": "1080x1920",
    "text_overlay": {
      "text": "Cara Cepat Viral!",
      "style": {
        "font_family": "Montserrat",
        "font_weight": "bold",
        "font_size": 120,
        "color": "#FFFFFF",
        "text_transform": "uppercase",
        "text_shadow": "3px 3px 5px #000000"
      },
      "background": {
        "color": "rgba(0, 0, 0, 0.5)",
        "padding": 40,
        "radius": 20
      },
      "position": {
        "y": "bottom",
        "margin_bottom": 300,
        "edge_padding": 80
      }
    },
    "export": {
      "format": "png"
    }
  }'
```

### Thumbnail Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `video_url` | string | optional | Video source for frame extraction |
| `background_image.url` | string | optional | Override with static image |
| `size` | string | "1080x1920" | Output size WxH |
| `frame_selection.mode` | string | "face_detection" | face_detection / timestamp |
| `frame_selection.prefer` | string | "centered" | centered / largest / most_active |

### Text Style Options

| Parameter | Example | Description |
|-----------|---------|-------------|
| `font_family` | "Montserrat" | Font name (supports fc-list fonts) |
| `font_weight` | "bold" | bold / regular / light |
| `font_size` | 120 | Font size in pixels |
| `color` | "#FFFFFF" | Text color (hex/rgba) |
| `text_transform` | "uppercase" | uppercase / lowercase / capitalize |
| `text_shadow` | "3px 3px 5px #000" | Shadow: x y blur color |
| `stroke_color` | "#000000" | Text outline color |
| `stroke_width` | 2 | Outline width in pixels |
| `line_height` | 1.2 | Multiplier (1.2 = 120% spacing) |
| `line_spacing` | 30 | Pixel value (overrides line_height) |
| `letter_spacing` | 5 | Extra pixels between characters |

### Position Object (`position`)

| Property | Default | Description |
|----------|---------|-------------|
| `position` | "bottom_right" | `top_left`, `top_center`, `top_right`, `center_left`, `center`, `center_right`, `bottom_left`, `bottom_center`, `bottom_right` |
| `margin_x` | 30 | Horizontal margin in **pixels** (e.g., 30) or **percentage** (e.g., "5%") |
| `margin_y` | 30 | Vertical margin in **pixels** (e.g., 30) or **percentage** (e.g., "10%") |
| `max_lines` | 3 | Max lines (truncate with ...) |

### Background Options

| Parameter | Default | Description |
|-----------|---------|-------------|
| `enabled` | true | Enable background |
| `gradient` | false | Enable gradient (solid bottom → transparent top) |
| `gradient_height` | 0 | Custom gradient height (0 = auto) |
| `color` | "rgba(0,0,0,0.7)" | Background color |
| `padding` | 40 | Padding inside box |
| `radius` | 20 | Corner radius (ignored if gradient) |
| `full_width` | true | 100% width of thumbnail |

---

## 5. Video Source Overlay

Tambahkan text overlay sumber video (channel name) dan logo pada video. **Synchronous** (langsung return URL).

```bash
curl -X POST http://host.docker.internal:8000/add_video_source \
  -H "Content-Type: application/json" \
  -d '{
    "video_url": "http://minio-video:9002/video-clips/job_xxx.mp4",
    "channel_name": "MyYoutube Channel",
    "prefix": "Watch full video on:",
    "logo_url": "http://minio-video:9002/logos/icon.png",
    "logo_scale": 1.2,
    "prefix_style": {
        "font_family": "Montserrat",
        "font_size": 30,
        "color": "#FF0000",
        "italic": true
    },
    "channel_style": {
        "font_family": "Komika Axis",
        "font_size": 40,
        "color": "#FFFFFF",
        "bold": true,
        "stroke_color": "#000000",
        "stroke_width": 2
    },
    "background": {
    "channel_style": {
        "font_family": "Montserrat",
        "font_size": 40,
        "color": "#FFFFFF",
        "bold": true,
        "italic": false,
        "stroke_color": "#000000",
        "stroke_width": 2
    },
    "position": {
        "position": "top_right",
        "margin_x": 40,
        "margin_y": 40
    }
  }'
```

### Video Source Parameters

| Name | Type | Description |
|------|------|-------------|
| `video_url` | string | **Required**. Video URL |
| `channel_name` | string | **Required**. Main text to display |
| `prefix` | string | Text prefix (default: "Source:") |
| `logo_url` | string | **Optional**. URL logo image (PNG recommended) |
| `logo_scale` | float | **Optional**. Scale logo relative to text height (default: 1.0) |
| `line_spacing` | int | **Optional**. Space between text lines (default: 8) |
| `logo_offset_y` | int | **Optional**. Vertical adjustment for logo (default: 0) |
| `logo_spacing` | int | **Optional**. Horizontal space between logo and text (default: 10) |
| `prefix_style` | object | Style for prefix text |
| `channel_style` | object | Style for channel text |
| `position` | object | Positioning settings |

### Style Object (`prefix_style` & `channel_style`)

| Property | Default | Description |
|----------|---------|-------------|
| `font_family` | "Montserrat" | Font name (e.g., "Komika Axis") |
| `font_size` | 40 | Font size in pixels |
| `color` | "#FFFFFF" | Text color (Hex/RGBA) |
| `bold` | true/false | Enable bold weight |
| `italic` | false | Enable italic style |
| `stroke_color` | null | Outline color (e.g., "#000000") |
| `stroke_width` | 0 | Outline width in pixels |

### Background Object

| Property | Default | Description |
|----------|---------|-------------|
| `enabled` | true | Show background box |
| `color` | "rgba(0,0,0,0.5)" | Background color |
### Position Options

| Position | Description |
|----------|-------------|
| `top_left` | Kiri atas |
| `top_center` | Tengah atas |
| `top_right` | Kanan atas |
| `center_left` | Tengah kiri |
| `center` | Tepat di tengah |
| `center_right` | Tengah kanan |
| `bottom_left` | Kiri bawah |
| `bottom_center` | Tengah bawah |
| `bottom_right` | Kanan bawah (default) |

---

## 6. Image Watermark

Tambahkan watermark gambar (logo, PNG dengan transparansi) pada video. **Synchronous** (langsung return URL).

```bash
curl -X POST http://host.docker.internal:8000/add_image_watermark \
  -H "Content-Type: application/json" \
  -d '{
    "video_url": "http://minio-video:9002/video-clips/job_xxx.mp4",
    "image_url": "http://minio-video:9002/logos/logo.png",
    "size": { "scale": 0.3 },
    "position": { "position": "bottom_right" },
    "opacity": 0.8
  }'
```

### Image Watermark Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `video_url` | string | required | URL of video source |
| `image_url` | string | required | URL of watermark image (PNG) |
| `size.width` | int | null | Target width in pixels |
| `size.height` | int | null | Target height in pixels |
| `size.scale` | float | null | Scale factor (0.3 = 30%) |
| `position.position` | string | "bottom_right" | Position on video |
| `position.margin_x` | int | 30 | Horizontal margin |
| `position.margin_y` | int | 30 | Vertical margin |
| `opacity` | float | 1.0 | Transparency (0.0 - 1.0) |

### Position Options

| Position | Description |
|----------|-------------|
| `top_left` | Kiri atas |
| `top_center` | Tengah atas |
| `top_right` | Kanan atas |
| `center` | Tengah |
| `bottom_left` | Kiri bawah |
| `bottom_center` | Tengah bawah |
| `bottom_right` | Kanan bawah (default) |

---


---

## 7. Overlay Notification (Green Screen)

Add a video overlay (like a subscribe button) onto a main video, with automatic or manual background removal.

**Endpoint:** `POST /overlay_notification`

**Payload:**
```json
{
  "video_url": "http://minio:9000/bucket/main.mp4",
  "overlay_url": "http://minio:9000/bucket/subscribe_green_screen.mp4",
  "start_time": "end-1.5", // "end", "end-2", "end+1" supported
  "position": {
    "preset": "bottom_right",
    "margin_x": 30,
    "margin_y": 30
  },
  "resize": {
    "scale": 0.5
  },
  "chroma_key": {
    "auto": true
  }
}
```

**Advanced Chroma Key:**
```json
  "chroma_key": {
    "auto": false,
    "color": "#00FF00",
    "similarity": 0.3,
    "blend": 0.1,
    "crop": true // Set to false to disable Smart Auto-Crop
  }
}
```

**Position Presets (`position.preset`):**

> **Note:** The system automatically applies **Smart Auto-Crop** (enabled by default) with a **safety padding** to accommodate animation movements. It removes empty background space before applying the position preset. You can disable this by setting `chroma_key.crop: false`.

| Preset | Position |
|--------|----------|
| `top_left` | Top Left |
| `top_center` | Top Center |
| `top_right` | Top Right |
| `center` | Center (Middle) |
| `bottom_left` | Bottom Left |
| `bottom_center` | Bottom Center |
| `bottom_right` | Bottom Right (Default) |

**Custom Position:**
To use custom coordinates (e.g., center with margin), remove `preset` and use `x`, `y` (supports FFmpeg variables like `main_w`, `overlay_w`).

```json
  "position": {
    "x": "(main_w-overlay_w)/2",
    "y": "main_h-overlay_h-50"
  }
```

---

## 8. Merge Videos

Gabungkan beberapa video menjadi satu. **Synchronous** (langsung return URL).

```bash
curl -X POST http://host.docker.internal:8000/merge_videos \
  -H "Content-Type: application/json" \
  -d '{
    "videos": [
      { "video_url": "http://minio-video:9002/video-clips/video1.mp4" },
      { "video_url": "http://minio-video:9002/video-clips/video2.mp4" }
    ]
  }'
```

Video akan digabung secara berurutan.

---

## 9. Image to Video

Buat video dari gambar (single atau slideshow).

```bash
# Example 1: Slideshow with Transition
curl -X POST http://host.docker.internal:8000/image_to_video \
  -H "Content-Type: application/json" \
  -d '{
    "images": [
      { "image_url": "http://minio-video:9002/images/1.jpg", "duration": 4.0 },
      { "image_url": "http://minio-video:9002/images/2.jpg", "duration": 4.0 },
      { "image_url": "http://minio-video:9002/images/3.jpg", "duration": 4.0 }
    ],
    "fps": 30,
    "transition": "dissolve",
    "callback_url": "https://your-domain.com/webhook"
  }'

# Example 2: Single Image with Motion (Ken Burns)
curl -X POST http://host.docker.internal:8000/image_to_video \
  -H "Content-Type: application/json" \
  -d '{
    "images": [
      { "image_url": "http://minio-video:9002/images/cover.jpg", "duration": 15.0 }
    ],
    "fps": 60,
    "motion": "zoom_in",
    "motion_intensity": 0.5
  }'
```

### Image to Video Parameters

| Parameter | Tipe | Default | Wajib? | Deskripsi |
|-----------|------|---------|--------|-----------|
| **`images`** | `list` | - | **YA** | Daftar gambar yang akan dijadikan video |
| `images[].image_url`| `str` | - | **YA** | URL gambar (support HTTP external & MinIO interneal) |
| `images[].duration` | `float`| `3.0` | Tidak | Durasi tampil per gambar (detik) |
| **`fps`** | `int` | `30` | Tidak | Frame rate output video |
| **`transition`** | `str` | `null` | Tidak | Efek transisi antar gambar (SlideShow only) |
| **`motion`** | `str` | `null` | Tidak | Efek gerak / Ken Burns (Single Image only) |
| **`motion_intensity`**| `float`| `0.3` | Tidak | Kekuatan efek motion (0.1 = halus, 1.0 = kuat/cepat) |
| **`callback_url`** | `str` | `null` | Tidak | Webhook URL untuk notifikasi saat job selesai |

### Transition Options (Slideshow)

| Category | Options |
|----------|---------|
| **Basic** | `fade`, `dissolve`, `pixelize` |
| **Wipe** | `wipeleft`, `wiperight`, `wipeup`, `wipedown` |
| **Slide** | `slideleft`, `slideright`, `slideup`, `slidedown` |
| **Shape** | `circleopen`, `circleclose`, `circlecrop`, `radial` |
| **Open/Close** | `horzopen`, `horzclose`, `vertopen`, `vertclose` |

### Motion Options (Single Image - Ken Burns)

| Motion | Description |
|--------|-------------|
| `zoom_in` | Zoom in dari tengah |
| `zoom_out` | Zoom out dari tengah |
| `pan_left` | Pan dari kanan ke kiri |
| `pan_right` | Pan dari kiri ke kanan |
| `pan_up` | Pan dari bawah ke atas |
| `pan_down` | Pan dari atas ke bawah |
| `zoom_in_pan_right` | Zoom + pan kanan |
| `zoom_in_pan_left` | Zoom + pan kiri |

---

## 10. Check Job Status

```bash
curl http://host.docker.internal:8000/job/{job_id}
```

---

## 11. Download Result

```bash
# External access (browser)
curl -o clip.mp4 "http://localhost:9002/video-clips/{job_id}.mp4"

# From n8n/Docker (nca-network)
# Use: http://minio-video:9002/video-clips/{job_id}.mp4
```

---

## Custom Fonts

1. Copy `.ttf` files to `video-worker/fonts/`
2. Rebuild: `docker-compose up -d --build video-worker`
3. Use in API: `"font_family": "FontName"`

---

## Features

### Face Tracking
- **Hybrid detection**: Face Detection + Face Mesh
- **Initial Scan**: Lock ke wajah paling AKTIF (bukan terbesar)
- **Lock Mode**: Tetap fokus pada speaker aktif + auto zoom
- **2-Person Dialog Mode**: Switch cepat untuk sensitivity ≥7 + 2 orang  
- **Lost Face Recovery**: Auto switch jika wajah hilang 0.5 detik
- **Dynamic Zoom**: Hingga 25% saat tertawa/speaking aktif
- **Smooth camera**: Configurable smoothing (default 0.25)

### Auto Caption
- **Whisper AI**: Indonesian language support
- **Word-level highlight**: Karaoke-style effect
- **Custom fonts**: Add your own .ttf files
- **Adjustable position**: Via margin_v parameter
- **Model cache**: Persisted across restarts

### Thumbnail Generator
- **Face Detection Frame**: Pilih frame terbaik dengan wajah menarik
- **Text Overlay**: Multi-line text dengan auto wrapping
- **Text Styling**: font, size, color, text_transform, text_shadow
- **Background Box**: Rounded rectangle dengan transparency
- **Edge Padding**: Configurable padding dari tepi frame
- **Multi-format**: PNG, JPG, WebP export

### Video Source Overlay
- **FFmpeg drawtext**: Text overlay dengan background box
- **Flexible positioning**: top_left, top_right, bottom_left, bottom_right
- **Auto URL conversion**: minio:9000/localhost:9000 → minio-nca:9000
- **Custom styling**: Font, size, color, background transparency

### Video Processing
- **Exact duration**: No extra buffer
- **Partial download**: Faster processing
- **High quality**: H.264 CRF 18

## 12. Media Metadata

Dapatkan metadata detail dari berbagai jenis media (YouTube, Video File, Audio File, Image File).

```bash
curl -X POST http://host.docker.internal:8000/media_info \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.youtube.com/watch?v=VIDEO_ID"
    // OR
    "media_url": "http://minio-video:9002/..."
  }'
```

### Media Info Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `url` | string | yes* | URL Media (YouTube / Direct File URL) |
| `media_url` | string | yes* | Alias for `url` (Use either one) |

### Response Examples

#### YouTube
```json
{
  "status": "success",
  "type": "video",
  "source": "youtube",
  "metadata": {
    "title": "Video Title",
    "channel": "Channel Name",
    "duration": 956,
    "width": 640,
    "height": 360,
    "thumbnail": "https://i.ytimg.com/...",
    "view_count": 100000
  }
}
```

#### Direct Media File (Video/Audio)
```json
{
  "status": "success",
  "type": "video",
  "source": "direct",
  "metadata": {
    "audio_bitrate": 192336,
    "audio_bitrate_kbps": 192,
    "audio_channels": 2,
    "audio_codec": "aac",
    "audio_codec_long": "AAC (Advanced Audio Coding)",
    "audio_sample_rate": 44100,
    "audio_sample_rate_khz": 44,
    "duration": 15.023311,
    "duration_formatted": "00:00:15.02",
    "filesize": 2498125,
    "filesize_mb": 2.38,
    "format": "mov,mp4,m4a,3gp,3g2,mj2",
    "has_audio": true,
    "has_video": true,
    "overall_bitrate": 1330266,
    "overall_bitrate_mbps": 1.33,
    "width": 1280,
    "height": 720,
    "video_codec": "h264",
    "video_codec_long": "H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10",
    "fps": 23.98
  }
}
```

```

---

## 12. Trim Video

Endpoint synchronous untuk memotong video berdasarkan start dan end time.

```bash
curl -X POST http://host.docker.internal:8000/trim \
  -H "Content-Type: application/json" \
  -d '{
    "video_url": "http://minio-nca:9000/video-clips/input.mp4",
    "start": "00:00:05",
    "end": "00:00:10.5",
    "video_codec": "libx264"
  }'
```

### Trim Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `video_url` | string | required | URL Video Source |
| `start` | string | required | Start time (e.g. `00:00:05` or `5.0`) |
| `end` | string | required | End time (e.g. `00:00:10` or `10.0`) |
| `video_codec` | string | "libx264" | Output video codec |
| `video_preset`| string | "faster" | Encoding preset (ultrafast - veryslow) |
| `video_crf` | int | 28 | Quality (Lower = Better, Higher = Smaller) |
| `audio_codec` | string | "aac" | Audio codec |
| `audio_bitrate`| string | "128k" | Audio bitrate |
| `id` | string | null | Custom ID for tracking |

### Response Format

Mengembalikan JSON List dengan detail job.

```json
[
  {
    "build_number": 1,
    "code": 200,
    "endpoint": "/v1/video/trim",
    "id": "custom-id",
    "job_id": "uuid-job-id",
    "message": "success",
    "response": "http://minio-nca:9000/video-clips/uuid_output.mp4",
    "run_time": 2.44,
    "total_time": 2.45
  }
]
```

```

---

## 13. Video Composer

Endpoint untuk membuat komando FFmpeg kompleks secara fleksibel.

```bash
```bash
curl -X POST http://host.docker.internal:8000/compose \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": [
      {
        "file_url": "http://minio-storage:9002/video-clips/video1.mp4"
      },
      {
        "url": "http://minio-storage:9002/video-clips/audio1.mp4"
      }
    ],
    "outputs": [
      {
        "options": [
          { "option": "-map", "argument": "0:v:0" },
          { "option": "-map", "argument": "1:a:0" },
          { "option": "-c:v", "argument": "copy" },
          { "option": "-c:a", "argument": "aac" },
          { "option": "-shortest" }
        ]
      }
    ]
  }'
```

### Compose Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `inputs` | list | required | List of input files |
| `inputs[].url` | string | required | Input URL (or `file_url`) |
| `inputs[].file_url` | string | optional | Alias for `url` |
| `inputs[].options`| list | [] | FFmpeg options applied *before* `-i` |
| `filter_complex` | string | null | FFmpeg filter string |
| `outputs` | list | [] | Structured output options |
| `outputs[].options` | list | [] | List of `{option, argument}` objects |
| `output_args` | list | [] | Legacy flat list of output arguments |
| `output_format`| string | "mp4" | Output file extension |

```

---

## 14. Add Video Source Overlay

Endpoint synchronous untuk menambahkan overlay teks (Source/Credit) ke video.

```bash
curl -X POST http://host.docker.internal:8000/add_video_source \
  -H "Content-Type: application/json" \
  -d '{
    "video_url": "http://minio-nca:9000/video-clips/input.mp4",
    "channel_name": "MyChannel",
    "prefix": "Source:",
    "position": { 
      "position": "bottom_right", 
      "margin_x": 30, 
      "margin_y": 30 
    },
    "prefix_style": { "color": "#FF0000", "bold": true },
    "channel_style": { "color": "#FFFFFF", "bold": true },
    "background": { "enabled": true, "color": "rgba(0,0,0,0.5)", "radius": 10 }
  }'
```

### Video Source Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `video_url` | string | required | Input Video URL |
| `channel_name`| string | required | Text to display as channel name |
| `prefix` | string | "FullVideo:"| Prefix text |
| `position` | object | bottom_right | `{position, margin_x, margin_y}` |
| `prefix_style` | object | {} | Font style for prefix |
| `channel_style`| object | {} | Font style for channel name |
| `background` | object | {} | Background box style |

---

## 15. Streamlit Dashboard

UI berbasis Web untuk memudahkan penggunaan pipeline tanpa curl command.

**URL**: `http://localhost:8501`

### Fitur Utama

1.  **Auto Fetch Data**
    *   Input URL YouTube.
    *   Otomatis ambil Judul, Channel Name, dan Thumbnail.
    *   **Smart Transcript**: Prioritas ambil subtitle bahasa indonesia.

2.  **Video Context (Clean UI)**
    *   Transcript disembunyikan secara default ("Hidden").
    *   Toggle **"👁️ Show/Edit Transcript"** untuk melihat atau mengedit teks secara manual.

3.  **Advanced Camera Settings**
    *   **Sensitivity (1-10)**: Mengatur kecepatan switch antar pembicara.
    *   **Smoothing (0.05-0.5)**: Mengatur kehalusan pergerakan kamera.
    *   **Zoom Threshold & Level**: Mengatur sensitivitas auto-zoom.

4.  **Caption Styling & Preview**
    *   **Live Preview**: Real-time visualisasi caption dengan **kalibrasi visual** (WYSIWYG).
    *   **Preset Manager**: Simpan/Load setting favorit Anda.
    *   **Collapsible Settings**: Pengaturan detail (Font, Color, Layout) tersimpan rapi dalam menu *accordion* agar tidak memenuhi layar.
    *   **Smart Scaling**: Preview outline width dan font size dikalibrasi agar sesuai dengan output video final.

5.  **Thumbnail Generator (Simplified)**
    *   **Automatic Text**: Otomatis menggunakan judul YouTube sebagai teks thumbnail.
    *   **No Manual Input**: Input teks manual dihapuskan untuk simplifikasi.
    *   **Visual Preview**: Langsung melihat hasil layout thumbnail sebelum generate.
    *   **Preset Support**: Simpan gaya thumbnail (font, warna background, posisi) sebagai preset (terpisah dari caption preset).

6.  **Automa Integration**
    *   **One-Click Submit**: Kirim job langsung ke endpoint webhook n8n.
    *   Payload mencakup URL, channel name, transcript, dan parameter kamera.

---

## Service Management

### 1. Restart All Services

Untuk merestart seluruh stack (API, Worker, Dashboard, Database):

```bash
# Restart containers only
docker-compose restart

# OR completely rebuild and start (Recommended for updates)
docker-compose down
docker-compose up -d --build
```

### 2. Restart Specific Services

Jika Anda hanya mengubah kode di satu service, cukup restart service tersebut:

#### Video Worker (Logic Processing)
Gunakan ini jika mengubah `worker.py`, `modules/*.py`, atau `fonts/`.

```bash
docker restart video_worker
# OR
docker-compose restart video-worker
```

#### Video API (Endpoints)
Gunakan ini jika mengubah `main.py` di `video-api`.

```bash
docker restart video_api
# OR
docker-compose restart video-api
```

#### Dashboard (Streamlit UI)
Gunakan ini jika mengubah `app.py` atau UI logic.

```bash
docker restart video_dashboard
# OR
docker-compose restart dashboard
```

### 3. View Logs

Memantau logs untuk debugging:

```bash
# Worker Logs (Processing loop)
docker logs video_worker -f

# API Logs (Requests)
docker logs video_api -f

# Dashboard Logs
docker logs video_dashboard -f
```

docker-compose restart video-worker