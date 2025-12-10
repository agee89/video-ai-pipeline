# CLAUDE.md

## Project Overview

**Video AI Pipeline** adalah sistem microservice untuk:
1. Auto-clipping video YouTube dengan face tracking
2. Menambahkan caption otomatis menggunakan Whisper AI

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   video-api     │───▶│     Redis       │◀───│  video-worker   │
│   (FastAPI)     │    │   (Job Queue)   │    │   (Python)      │
│   Port: 8000    │    │                 │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                                       │
                                                       ▼
                                              ┌─────────────────┐
                                              │     MinIO       │
                                              │  (S3 Storage)   │
                                              │  Port: 9002     │
                                              └─────────────────┘
```

## Directory Structure

```
video-ai-pipeline/
├── docker-compose.yml
├── .env
├── Readme.md
├── CLAUDE.md
├── storage/output/
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
        └── video_merge.py   # Video concatenation
```

## API Endpoints

### POST /process_video
Clip video dari YouTube dengan opsi portrait + face tracking.

```json
{
  "youtube_url": "https://youtube.com/watch?v=...",
  "start_time": "1:30",
  "end_time": "2:45",
  "portrait": true,
  "face_tracking": true,
  "tracking_sensitivity": 5,
  "camera_smoothing": 0.15,
  "callback_url": "https://webhook.example.com"
}
```

**Face Tracking Parameters:**

| Parameter | Range | Default | Function |
|-----------|-------|---------|----------|
| `tracking_sensitivity` | 1-10 | 5 | Switch speed between speakers |
| `camera_smoothing` | 0.05-0.5 | 0.25 | Camera movement speed |

**New Features:**
- **Lock Mode**: Kamera terkunci pada speaker aktif + auto zoom
- **2-Person Dialog Mode**: Mode cepat untuk sensitivity ≥7 + 2 orang
- **Lost Face Recovery**: Auto switch jika wajah hilang 0.5 detik
- **Dynamic Zoom**: Hingga 25% zoom saat tertawa/speaking

**Recommended Combinations:**
- Interview: `sensitivity=3, smoothing=0.15`
- Podcast 2 orang: `sensitivity=7, smoothing=0.25`
- Panel diskusi: `sensitivity=5, smoothing=0.20`
- Dialog dinamis: `sensitivity=9, smoothing=0.30`

> Detail: [FACE_TRACKING.md](./FACE_TRACKING.md)

### POST /add_video_source
Tambahkan text overlay sumber video (channel name) pada video.

```json
{
  "video_url": "http://minio-video:9002/video-clips/job_xxx.mp4",
  "channel_name": "MyYoutube Channel",
  "prefix": "FullVideo:",
  "text_style": {
    "font_family": "Montserrat",
    "font_size": 40,
    "color": "#FFFFFF",
    "bold": true
  },
  "background": {
    "enabled": true,
    "color": "rgba(0, 0, 0, 0.5)",
    "padding": 20
  },
  "position": {
    "position": "bottom_right",
    "margin_x": 30,
    "margin_y": 30
  }
}
```

**Position Options:** `top_left`, `top_right`, `bottom_left`, `bottom_right` (default)

**Minimal Request:**
```json
{
  "video_url": "http://minio-video:9002/video-clips/job_xxx.mp4",
  "channel_name": "MyYoutube Channel"
}
```
Output: Video dengan text "FullVideo: MyYoutube Channel" di pojok kanan bawah.

### POST /add_image_watermark
Tambahkan watermark gambar (logo) pada video.

```json
{
  "video_url": "http://minio-video:9002/video-clips/job_xxx.mp4",
  "image_url": "http://minio-video:9002/logos/logo.png",
  "size": {
    "scale": 0.3
  },
  "position": {
    "position": "bottom_right",
    "margin_x": 20,
    "margin_y": 20
  },
  "opacity": 0.8
}
```

**Size Options:** `width`, `height`, `scale` (e.g. 0.3 = 30%)

**Position Options:** `top_left`, `top_center`, `top_right`, `center`, `bottom_left`, `bottom_center`, `bottom_right`

**Minimal Request:**
```json
{
  "video_url": "http://minio-video:9002/video-clips/job_xxx.mp4",
  "image_url": "http://minio-video:9002/logos/logo.png"
}
```

### POST /merge_videos
Gabungkan beberapa video menjadi satu.

```json
{
  "videos": [
    { "video_url": "http://minio:9000/bucket/video1.mp4" },
    { "video_url": "http://minio-video:9002/video-clips/video2.mp4" }
  ]
}
```

Video akan digabung secara berurutan (video1 → video2 → ...).

### POST /add_captions
Tambahkan caption ke video menggunakan Whisper.

```json
{
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
  },
  "callback_url": "https://webhook.example.com"
}
```

### POST /transcribe_youtube
Dapatkan transcript dari video YouTube dengan timestamps.

**Mode 1: YouTube Transcript (Default - CEPAT)**
```json
{
  "youtube_url": "https://youtube.com/watch?v=...",
  "language": "id"
}
```

**Mode 2: Whisper AI (AKURAT)**
```json
{
  "youtube_url": "https://youtube.com/watch?v=...",
  "language": "id",
  "use_whisper": true,
  "model": "medium"
}
```

Parameters:
| Parameter | Default | Description |
|-----------|---------|-------------|
| youtube_url | required | YouTube URL |
| language | "id" | Language code |
| use_whisper | false | false=YouTube (fast), true=Whisper (accurate) |
| model | "medium" | Whisper model (hanya jika use_whisper=true) |
| start_time | null | Optional start time |
| end_time | null | Optional end time |

Response:
```json
{
  "video_id": "abc123",
  "source": "youtube",
  "transcript": {
    "text": "Full text...",
    "segments": [
      {"start": 0.0, "end": 3.5, "text": "First sentence"}
    ]
}
```

> **Fallback**: Jika YouTube transcript tidak tersedia, otomatis menggunakan Whisper.

### POST /generate_thumbnail
Generate thumbnail dengan face detection dan text overlay.

```json
{
  "video_url": "http://video.mp4",
  "size": "1080x1920",
  "frame_selection": {
    "mode": "face_detection",
    "prefer": "centered"
  },
  "text_overlay": {
    "text": "CARA CEPAT VIRAL!",
    "style": {
      "font_family": "Komika Axis",
      "font_weight": "bold",
      "font_size": 150,
      "color": "#FFFC51",
      "text_transform": "uppercase",
      "text_shadow": "3px 3px 5px #000000",
      "line_height": 1.2,
      "letter_spacing": 3
    },
    "background": {
      "color": "rgba(0, 0, 0, 0.5)",
      "padding": 40,
      "radius": 0,
      "full_width": true
    },
    "position": {
      "x": "center",
      "y": "bottom",
      "margin_bottom": 250,
      "edge_padding": 40,
      "max_lines": 4
    }
  },
  "export": {
    "format": "png"
  }
}
```

**Text Style Options:**
| Parameter | Description |
|-----------|-------------|
| font_family | Font name (uses fc-list) |
| font_size | Size in pixels |
| text_transform | uppercase / lowercase / capitalize |
| text_shadow | "x y blur color" format |
| line_height | Multiplier (1.2 = 120%) |
| line_spacing | Pixels (overrides line_height) |
| letter_spacing | Extra pixels between chars |
| stroke_color/width | Text outline |

**Background Options:** enabled, gradient (solid bottom → transparent top), gradient_height, color, padding, radius, full_width

### GET /job/{job_id}
Check status job.

## Key Modules

### thumbnail.py - Thumbnail Generator
- **Face Detection Frame**: Pilih frame terbaik dengan wajah menarik via fc-list
- **Text Overlay**: Multi-line dengan auto wrapping + letter spacing
- **Full Width Background**: 100% lebar dengan padding proporsional
- **Font Metrics**: Actual text height untuk alignment sempurna
- **Multi-format**: PNG, JPG, WebP export

### portrait.py - Face Tracking
- **Hybrid approach**: Face Detection (wide shot) + Face Mesh (lip tracking)
- **Initial Scan**: Lock ke wajah paling AKTIF (bukan terbesar)
- **Lock Mode**: Tetap fokus pada speaker aktif + auto zoom
- **2-Person Dialog Mode**: Switch cepat untuk sensitivity ≥7 + 2 orang
- **Lost Face Recovery**: Auto switch jika wajah hilang 0.2 detik
- **Dynamic Zoom**: Hingga 25% zoom saat tertawa/speaking aktif
- **Smooth camera**: Configurable via `camera_smoothing` (default 0.25)

### captioner.py - Auto Caption
- **Whisper models**: tiny, base, small, medium, large
- **Word-level timestamps**: Karaoke-style highlighting
- **ASS subtitles**: Rich styling support
- **Model cache**: Persisted in Docker volume

### video_source.py - Video Source Overlay
- **FFmpeg drawtext**: Text overlay dengan background box
- **Flexible positioning**: 9 posisi (top_left, bottom_right, etc.)
- **URL conversion**: Auto-convert minio:9000/localhost:9000 → minio-nca:9000
- **Styling options**: Font, size, color, background transparency

### image_watermark.py - Image Watermark
- **FFmpeg overlay**: Image overlay dengan alpha support
- **Resize options**: width, height, atau scale factor
- **7 positions**: top_left, top_center, top_right, center, bottom_left, bottom_center, bottom_right
- **Opacity control**: 0.0 - 1.0 transparency

### video_merge.py - Video Merge
- **FFmpeg concat**: Concatenate multiple videos
- **Stream copy**: Fast processing when codecs match
- **Re-encoding fallback**: Auto re-encode if stream copy fails

## Docker Volumes

| Volume | Purpose |
|--------|---------|
| `minio_data` | MinIO storage data |
| `whisper_cache` | Whisper model cache |

## Networks

| Network | Purpose |
|---------|---------|
| `pipe-network` | Internal communication |
| `youtubeautomation_nca-network` | n8n integration |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `STORAGE_ENDPOINT` | MinIO internal URL |
| `STORAGE_N8N_URL` | MinIO URL for n8n |
| `STORAGE_PUBLIC_URL` | MinIO URL for browser |
| `REDIS_URL` | Redis connection |

## URL Access

| Context | URL |
|---------|-----|
| Browser | `http://localhost:9002/video-clips/...` |
| video-worker | `http://minio:9002/video-clips/...` |
| n8n | `http://minio-video:9002/video-clips/...` |
| API | `http://host.docker.internal:8000/...` |
| External MinIO (NCAT) | `http://minio-nca:9000/...` |

> **Note**: URL dari NCAT toolkit (`minio:9000` atau `localhost:9000`) otomatis dikonversi ke `minio-nca:9000` oleh video_source.py

## Custom Fonts

1. Copy `.ttf` to `video-worker/fonts/`
2. Rebuild: `docker-compose up -d --build video-worker`
3. Use in API: `"font_family": "FontName"`

## Development Commands

```bash
# Start all services
docker-compose up -d

# Rebuild after code changes
docker-compose up -d --build video-worker

# View logs
docker logs video_worker -f

# Check containers
docker ps -a | grep video

# Stop all
docker-compose down
```

## Git Commands

```bash
# Check status
git status

# Add all changes
git add .

# Commit with message
git commit -m "Deskripsi perubahan"

# Push to remote
git push

# One-liner: add, commit, push
git add . && git commit -m "Deskripsi perubahan" && git push

# Pull latest changes
git pull

# View commit history
git log --oneline -10
```

## Whisper Models

| Model | Size | RAM | Quality |
|-------|------|-----|---------|
| tiny | 39 MB | ~1 GB | Basic |
| base | 74 MB | ~1 GB | Good |
| small | 244 MB | ~2 GB | Better |
| medium | 769 MB | ~5 GB | Best for Indonesian |
| large | 1.5 GB | ~10 GB | Best overall |

## Caption Settings

| Setting | Default | Description |
|---------|---------|-------------|
| font_family | Montserrat | Font name |
| font_size | 60 | Size in pixels |
| line_color | #FFFFFF | Default text color |
| word_color | #FFDD5C | Highlight color |
| all_caps | true | Uppercase text |
| max_words_per_line | 3 | Words per line |
| bold | true | Bold text |
| outline_width | 3 | Outline thickness |
| shadow_offset | 2 | Shadow distance |
| margin_v | 640 | Vertical margin (640 = 2/3 from top) |
| position | bottom_center | Position on screen |

## Troubleshooting

### Worker crashed (OOM)
- Use smaller Whisper model
- Increase Docker RAM limit

### No face detected
- Check detection rate in logs
- Lower tracking_sensitivity

### Caption position wrong
- Adjust margin_v (0 = bottom, 960 = middle, 1920 = top)

### Custom font not working
- Ensure .ttf file is in fonts/
- Rebuild container
- Check font name matches exactly

### Video source external MinIO error
- Pastikan external MinIO memiliki alias `minio-nca` di network
- Video URL akan auto-convert: `minio:9000` → `minio-nca:9000`
- Cek network connectivity: `docker exec video_worker python3 -c "import requests; r = requests.get('http://minio-nca:9000'); print(r.status_code)"`
