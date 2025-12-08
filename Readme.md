# Video AI Pipeline

Auto-clipping YouTube videos dengan face tracking, active speaker detection, dan auto-caption.

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
    "tracking_sensitivity": 8
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
| `tracking_sensitivity` | int | 5 | 1-10 (1=slow smooth, 10=faster) |

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
- **Wide shot support**: Works with 2+ people
- **Active speaker tracking**: Follows the speaker
- **Smooth transitions**: No jumpy camera

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