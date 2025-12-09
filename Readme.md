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
        └── callback.py      # Webhook notifications
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
| `camera_smoothing` | float | 0.15 | 0.05-0.5 (higher = faster camera movement) |

### Face Tracking Parameters Guide

#### How Face Tracking Works

1. **Initial Scan**: Sistem scan 15 frame pertama untuk menemukan wajah terbaik (ukuran × confidence)
2. **Hybrid Detection**: Face Detection (jarak jauh) + Face Mesh (lip tracking)
3. **Priority**: Wajah terbesar & paling aktif (bicara + bergerak) mendapat prioritas
4. **Fallback**: Jika tidak ada activity, otomatis fokus ke wajah terbesar
5. **Dynamic Zoom**: Otomatis zoom-in 15% saat subject tertawa/terkejut (mulut terbuka lebar)

#### `tracking_sensitivity` (1-10)

Mengontrol seberapa cepat kamera **berpindah antar orang** ketika mendeteksi speaker yang berbeda.

| Value | Behavior | Best For |
|-------|----------|----------|
| 1-3 | Sangat stabil, jarang switch | 1 speaker utama, interview |
| 4-6 | Balanced (default: 5) | Podcast 2 orang, dialog |
| 7-8 | Responsif, cepat pindah | Talk show, diskusi grup |
| 9-10 | Sangat agresif switching | Video dengan banyak speaker bergantian |

**Cara kerja**: Nilai rendah membutuhkan orang lain **jauh lebih aktif** (bicara + bergerak) sebelum kamera pindah. Nilai tinggi membuat kamera lebih mudah pindah ke siapapun yang terlihat aktif.

#### `camera_smoothing` (0.05-0.5)

Mengontrol **kecepatan pergerakan kamera** saat mengikuti wajah.

| Value | Speed | Effect |
|-------|-------|--------|
| 0.05 | Sangat lambat | Sinematik, smooth, cocok untuk konten formal |
| 0.10 | Lambat | Transisi halus |
| 0.15 | Medium (default) | Balance antara smooth dan responsif |
| 0.25 | Cepat | Tracking lebih ketat |
| 0.35 | Sangat cepat | Hampir real-time tracking |
| 0.50 | Instant | Mengikuti wajah tanpa delay |

#### Rekomendasi Kombinasi

| Skenario | sensitivity | smoothing | Catatan |
|----------|-------------|-----------|---------|
| Interview 1 orang | 2 | 0.10 | Fokus tetap, transisi halus |
| Podcast 2 orang | 5 | 0.15 | Balanced switching |
| Talk show / panel | 8 | 0.25 | Responsif multi-speaker |
| Vlog / energik | 9 | 0.35 | Tracking ketat |
| Wide shot 3-4 orang | 3 | 0.20 | Prioritas wajah terbesar |

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

## 4. Check Job Status

```bash
curl http://host.docker.internal:8000/job/{job_id}
```

---

## 5. Download Result

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
- **Multi-person support**: Tracks 2-4+ people in frame
- **Activity tracking**: Lip movement + body movement detection
- **Dynamic switching**: Sensitivity controls switch speed
- **Smooth camera**: Configurable smoothing (0.05-0.5)
- **Expression zoom**: Auto zoom-in saat tertawa/terkejut (max 15%)

### Auto Caption
- **Whisper AI**: Indonesian language support
- **Word-level highlight**: Karaoke-style effect
- **Custom fonts**: Add your own .ttf files
- **Adjustable position**: Via margin_v parameter
- **Model cache**: Persisted across restarts

### Video Processing
- **Exact duration**: No extra buffer
- **Partial download**: Faster processing
- **High quality**: H.264 CRF 18