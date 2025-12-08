# CLAUDE.md

## Project Overview

**Video AI Pipeline** adalah sistem microservice untuk auto-clipping video YouTube. Sistem ini mengunduh video dari YouTube, memotong video menjadi clips, dan mengkonversi ke format portrait (9:16) dengan face tracking untuk social media.

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
                                              │  Port: 9002/    │
                                              │        9003     │
                                              └─────────────────┘
```

### Components

1. **video-api** (`/video-api/`)
   - FastAPI REST API untuk menerima job requests
   - Endpoints: `POST /process_video`, `GET /job/{job_id}`, `GET /health`
   - Menyimpan job ke Redis queue

2. **video-worker** (`/video-worker/`)
   - Background worker yang memproses video jobs dari Redis
   - Processing pipeline: download → portrait/face-tracking → upload

3. **Redis**
   - Job queue (`video_jobs` list)
   - Job status storage (`job:{job_id}:status`, `job:{job_id}:result`, `job:{job_id}:error`)

4. **MinIO**
   - S3-compatible object storage untuk menyimpan video clips
   - API port: 9002, Console: 9003
   - Connected to multiple networks for n8n integration

## Directory Structure

```
video-ai-pipeline/
├── docker-compose.yml     # Docker orchestration
├── .env                   # Environment variables
├── Readme.md              # Usage notes
├── CLAUDE.md              # This file - project documentation
├── storage/               # Local storage (output files)
├── video-api/
│   ├── Dockerfile
│   ├── main.py            # FastAPI application
│   └── requirements.txt
└── video-worker/
    ├── Dockerfile
    ├── worker.py          # Main worker loop
    ├── requirements.txt
    └── modules/
        ├── fetcher.py     # YouTube download (partial/full)
        ├── portrait.py    # Portrait mode + HYBRID face tracking
        ├── exporter.py    # S3/MinIO upload (dual URL support)
        └── callback.py    # Webhook callback
```

## Key Technologies

- **Python 3.11**
- **FastAPI** - REST API framework
- **Redis** - Job queue & status storage
- **yt-dlp** - YouTube video downloader (supports partial download)
- **FFmpeg** - Video processing (cutting, encoding, reframing)
- **MediaPipe** - Face Detection + Face Mesh for hybrid tracking
- **OpenCV** - Video frame processing
- **boto3** - S3/MinIO client
- **Docker Compose** - Container orchestration

## Development Commands

```bash
# Create network (required first time)
docker network create pipe-network

# Start all services
docker-compose up -d

# View worker logs
docker logs video_worker -f

# Stop all services
docker-compose down

# Rebuild after code changes
docker-compose up -d --build video-worker
```

## API Usage

### Submit Video Processing Job

```bash
curl -X POST http://localhost:8000/process_video \
  -H "Content-Type: application/json" \
  -d '{
    "youtube_url": "https://www.youtube.com/watch?v=VIDEO_ID",
    "start_time": "1:30",
    "end_time": "2:45",
    "portrait": true,
    "face_tracking": true,
    "tracking_sensitivity": 5,
    "callback_url": "https://your-webhook.com/callback"
  }'
```

**Request Parameters:**
- `youtube_url` (required): YouTube video URL
- `start_time` (required): Start time in format `mm:ss` or `hh:mm:ss`
- `end_time` (required): End time in format `mm:ss` or `hh:mm:ss`
- `portrait` (optional, default: false): Convert clip to 9:16 portrait
- `face_tracking` (optional, default: false): Enable hybrid face detection
- `tracking_sensitivity` (optional, default: 5): 1-10 scale for camera movement
  - 1-3: Slow, very smooth transitions
  - 4-6: Balanced (recommended)
  - 7-10: Faster response
- `callback_url` (optional): Webhook URL for job completion notification

### Check Job Status

```bash
curl http://localhost:8000/job/{job_id}
```

**Response:**
```json
{
  "job_id": "job_abc123",
  "status": "completed",
  "clip": {
    "url": "http://minio-video:9002/video-clips/job_abc123.mp4",
    "url_external": "http://localhost:9002/video-clips/job_abc123.mp4",
    "start_time": 90,
    "end_time": 165,
    "duration": 75,
    "portrait": true,
    "face_tracking": true
  },
  "error": null
}
```

## Face Tracking System (Hybrid Approach)

The system uses a **hybrid detection approach** for reliable face tracking:

### 1. Face Detection (Primary)
- Uses `MediaPipe Face Detection` with `model_selection=1` (full range)
- **Optimized for wide shots** - works when faces are small/distant
- Detects face bounding boxes reliably even in podcast setups with 2+ people
- Expected detection rate: **>80%** of frames

### 2. Face Mesh (Secondary)  
- Uses `MediaPipe Face Mesh` for detailed facial landmark tracking
- **Optimized for close-ups** - detects lip movement for speaker identification
- Provides activity score based on lip opening (speech detection)
- Used to determine WHO is speaking, not WHERE faces are

### Tracking Logic
1. Face Detection finds all faces in frame
2. Face Mesh analyzes lip movement for visible faces
3. System tracks the **most active person** (highest lip activity)
4. Switching to another person requires **2x more activity**
5. If no faces detected, system **holds last position** (no jump to center)

### Activity Scoring
```
activity_score = lip_movement + size_bonus
```
- Lip movement: Accumulated lip opening changes over time
- Size bonus: Larger faces get slight preference
- Switch threshold: New person needs 2x activity AND >1.0 absolute score

## Worker Processing Pipeline

1. **Download** (`fetcher.py`): 
   - Tries partial download first using `yt-dlp --download-sections`
   - Falls back to full download + FFmpeg extraction if partial fails
   - **Exact duration**: No extra buffer time added

2. **Portrait** (`portrait.py`): Conversion to 9:16 with:
   - Center crop (if face_tracking=false), OR
   - **Hybrid face tracking** (if face_tracking=true):
     - Face Detection for reliable face finding
     - Face Mesh for lip/speaker tracking
     - Smooth camera transitions

3. **Upload** (`exporter.py`): 
   - Uploads to MinIO/S3
   - Returns **dual URLs**:
     - `url`: For n8n/Docker containers (`minio-video:9002`)
     - `url_external`: For browser access (`localhost:9002`)

4. **Callback** (`callback.py`): Webhook notification if callback_url provided

## Network Configuration

### MinIO Multi-Network Setup
MinIO is connected to multiple Docker networks:

1. **pipe-network** (default)
   - Internal: `minio:9002`
   - Used by: video-api, video-worker

2. **youtubeautomation_nca-network** (external)
   - Alias: `minio-video:9002`
   - Used by: n8n and other containers on that network

### URL Access
| Context | URL Format |
|---------|------------|
| Browser | `http://localhost:9002/video-clips/...` |
| video-worker | `http://minio:9002/video-clips/...` |
| n8n | `http://minio-video:9002/video-clips/...` |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `S3_BUCKET_NAME` | MinIO bucket name | video-clips |
| `S3_ACCESS_KEY` | MinIO access key | minioadmin |
| `S3_SECRET_KEY` | MinIO secret key | minioadmin |
| `REDIS_URL` | Redis connection URL | redis://redis:6379 |
| `STORAGE_ENDPOINT` | MinIO internal endpoint | http://minio:9002 |
| `STORAGE_N8N_URL` | MinIO URL for n8n | http://minio-video:9002 |
| `STORAGE_PUBLIC_URL` | MinIO URL for browser | http://localhost:9002 |

## Video Processing Notes

- **Partial Download**: System downloads only the requested segment (no buffer)
- **Exact Duration**: Output duration matches `end_time - start_time` exactly
- **Encoding**: H.264 (libx264) with CRF 18 (visually lossless)
- **Preset**: `fast` for face tracking, `slow` for simple crop
- **Audio**: AAC at 192kbps
- **Portrait**: 9:16 aspect ratio, scaled to 1080xN
- **Web Optimized**: `+faststart` flag for instant playback

## Testing

```bash
# Download clip from MinIO
curl -o test_clip.mp4 "http://localhost:9002/video-clips/clip_name.mp4"

# Check dimensions (expect 1080x1920 for portrait)
ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 test_clip.mp4

# Check duration
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 test_clip.mp4
```

## Troubleshooting

### Face tracking not working in wide shots
- Check logs for `detection rate` - should be >80%
- If low, faces may be too small or angled

### Video stuck at center
- This happens when no faces are detected
- The hybrid system should prevent this in most cases
- Check if video has recognizable human faces

### Wrong duration  
- Ensure `start_time` and `end_time` are correct
- Output should match exactly (no buffer added)
