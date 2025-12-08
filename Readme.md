# Video AI Pipeline

Auto-clipping YouTube videos dengan face tracking dan active speaker detection.

## Quick Start

```bash
# Start services
docker-compose up -d

# Monitor logs
docker logs video_worker -f
```

## Submit Job

```bash
curl -X POST http://localhost:8000/process_video \
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

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `youtube_url` | string | required | YouTube URL |
| `start_time` | string | required | Format: `mm:ss` or `hh:mm:ss` |
| `end_time` | string | required | Format: `mm:ss` or `hh:mm:ss` |
| `portrait` | bool | false | Convert to 9:16 portrait |
| `face_tracking` | bool | false | Enable active speaker tracking |
| `tracking_sensitivity` | int | 5 | 1-10 (1=slow smooth, 10=faster) |

## Check Status

```bash
curl http://localhost:8000/job/{job_id}
```

## Download Clip

```bash
# External access (browser)
curl -o clip.mp4 "http://localhost:9002/video-clips/{job_id}.mp4"

# From n8n/Docker containers on nca-network
# Use: http://minio-video:9002/video-clips/{job_id}.mp4
```

## Features

### Face Tracking (Hybrid Detection)
- **Face Detection** (primary): Works for wide shots, distant faces (2+ people podcast)
- **Face Mesh** (secondary): Lip movement tracking for close-up speaker detection
- **Activity-based switching**: Automatically follows the most active person (speaking/moving)
- **Smooth transitions**: No jumpy camera movement

### Video Processing
- **Exact duration**: Output matches requested start/end time exactly
- **Partial download**: Only downloads needed segment when possible
- **High quality**: H.264 CRF 18 (visually lossless)
- **Web optimized**: `+faststart` for instant playback

## API Response

```json
{
  "job_id": "job_abc123",
  "status": "completed",
  "clip": {
    "url": "http://minio-video:9002/video-clips/job_abc123.mp4",
    "url_external": "http://localhost:9002/video-clips/job_abc123.mp4",
    "start_time": 150,
    "end_time": 180,
    "duration": 30,
    "portrait": true,
    "face_tracking": true
  }
}
```

## Network Configuration

- **Internal port**: MinIO runs on port 9002 (API) and 9003 (console)
- **External access**: `http://localhost:9002/...`
- **Docker network**: Connected to both `pipe-network` and `youtubeautomation_nca-network`
- **n8n access**: Use alias `minio-video:9002`