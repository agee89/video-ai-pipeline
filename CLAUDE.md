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
        └── callback.py      # Webhook notifications
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
| `camera_smoothing` | 0.05-0.5 | 0.15 | Camera movement speed |

**Recommended Combinations:**
- Interview: `sensitivity=2, smoothing=0.10`
- Podcast 2 orang: `sensitivity=5, smoothing=0.15`
- Panel diskusi: `sensitivity=8, smoothing=0.25`
- Multi-speaker energik: `sensitivity=9, smoothing=0.35`

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
}
```

> **Fallback**: Jika YouTube transcript tidak tersedia, otomatis menggunakan Whisper.

### GET /job/{job_id}
Check status job.

## Key Modules

### portrait.py - Face Tracking
- **Hybrid approach**: Face Detection (wide shot) + Face Mesh (lip tracking)
- **Multi-person support**: Tracks most active person (lip + body movement)
- **Dynamic switching**: Sensitivity controls switch threshold (1-10)
- **Smooth camera**: Configurable via `camera_smoothing` (0.05-0.5)
- **Movement detection**: Detects body/head movement for activity scoring

### captioner.py - Auto Caption
- **Whisper models**: tiny, base, small, medium, large
- **Word-level timestamps**: Karaoke-style highlighting
- **ASS subtitles**: Rich styling support
- **Model cache**: Persisted in Docker volume

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
