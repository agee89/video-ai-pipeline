# Video AI Pipeline

Auto-clipping YouTube videos dengan face tracking, active speaker detection, dan auto-caption.

## Directory Structure

```
video-ai-pipeline/
├── docker-compose.yml       # Docker orchestration
├── .env                     # Environment variables
├── Readme.md                # This file
├── CLAUDE.md                # AI assistant context
├── storage/output/          # Local output storage
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
        └── video_source.py  # Video source overlay
```

---

## Quick Start

```bash
# Start services
docker-compose up -d

# Monitor logs
docker logs video_worker -f
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
    "camera_smoothing": 0.25
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
| `tracking_sensitivity` | int | 5 | 1-10 (1=stay longer, 10=switch faster) |
| `camera_smoothing` | float | 0.25 | 0.05-0.5 (higher = faster camera movement) |

### Face Tracking Parameters Guide

#### How Face Tracking Works

1. **Initial Scan**: Sistem scan ~1 detik pertama untuk menemukan wajah **PALING AKTIF** (bukan terbesar)
2. **Hybrid Detection**: Face Detection (jarak jauh) + Face Mesh (lip tracking)
3. **Lock Mode**: Saat fokus pada speaker aktif, kamera tetap terkunci dan zoom in
4. **2-Person Dialog Mode**: Mode khusus untuk 2 orang + sensitivity tinggi (≥7) - switch lebih cepat
5. **Lost Face Recovery**: Jika wajah hilang 0.5 detik, otomatis switch ke wajah yang terlihat
6. **Dynamic Zoom**: Otomatis zoom-in hingga **25%** saat tertawa/terkejut/speaking aktif

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
  "camera_smoothing": 0.15
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

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `video_url` | string | required | URL of video (MinIO or external) |
| `language` | string | "id" | Language code for Whisper |
| `model` | string | "medium" | Whisper model (see below) |
| `settings.font_family` | string | "Montserrat" | Font name |
| `settings.font_size` | int | 60 | Font size in pixels |
| `settings.line_color` | string | "#FFFFFF" | Default text color |
| `settings.word_color` | string | "#FFDD5C" | Highlight color |
| `settings.all_caps` | bool | true | Convert to uppercase |
| `settings.max_words_per_line` | int | 3 | Words per line |
| `settings.margin_v` | int | 640 | Vertical margin (640 = 2/3 from top) |
| `settings.position` | string | "bottom_center" | Caption position |

### Whisper Models

| Model | Size | RAM | Quality | Speed |
|-------|------|-----|---------|-------|
| `tiny` | 39 MB | ~1 GB | Basic | Fastest |
| `base` | 74 MB | ~1 GB | Good | Fast |
| `small` | 244 MB | ~2 GB | Better | Medium |
| `medium` | 769 MB | ~5 GB | Best for ID | Slow |
| `large` | 1.5 GB | ~10 GB | Best | Slowest |

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

### Position Options

| Parameter | Default | Description |
|-----------|---------|-------------|
| `x` | "center" | left / center / right / pixel |
| `y` | "bottom" | top / center / bottom / pixel |
| `margin_bottom` | 250 | Distance from bottom |
| `edge_padding` | 40 | Min padding from frame edges |
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

Tambahkan text overlay sumber video (channel name) pada video.

```bash
curl -X POST http://host.docker.internal:8000/add_video_source \
  -H "Content-Type: application/json" \
  -d '{
    "video_url": "http://minio-video:9002/video-clips/job_xxx.mp4",
    "channel_name": "MyYoutube Channel"
  }'
```

Output: Video dengan text **"FullVideo: MyYoutube Channel"** di pojok kanan bawah.

### Video Source Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `video_url` | string | required | URL of video source |
| `channel_name` | string | required | Channel name to display |
| `prefix` | string | "FullVideo:" | Text before channel name |
| `text_style.font_family` | string | "Montserrat" | Font name |
| `text_style.font_size` | int | 40 | Font size in pixels |
| `text_style.color` | string | "#FFFFFF" | Text color |
| `text_style.bold` | bool | true | Bold text |
| `background.enabled` | bool | true | Enable background box |
| `background.color` | string | "rgba(0,0,0,0.5)" | Background color |
| `background.padding` | int | 20 | Box padding |
| `position.position` | string | "bottom_right" | Position on video |
| `position.margin_x` | int | 30 | Horizontal margin |
| `position.margin_y` | int | 30 | Vertical margin |

### Position Options

| Position | Description |
|----------|-------------|
| `top_left` | Kiri atas |
| `top_right` | Kanan atas |
| `bottom_left` | Kiri bawah |
| `bottom_right` | Kanan bawah (default) |

---

## 6. Check Job Status

```bash
curl http://host.docker.internal:8000/job/{job_id}
```

---

## 7. Download Result

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