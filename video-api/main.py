from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, field_validator
from typing import Optional, Dict, Any
import uuid
import redis
import json
import os
import re

app = FastAPI(title="Video Clipping API")

redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))

def parse_time_to_seconds(time_str: str) -> float:
    """
    Parse waktu format mm:ss atau hh:mm:ss ke detik
    """
    parts = time_str.split(':')
    if len(parts) == 2:  # mm:ss
        return int(parts[0]) * 60 + float(parts[1])
    elif len(parts) == 3:  # hh:mm:ss
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    else:
        raise ValueError(f"Invalid time format: {time_str}")

class ProcessVideoRequest(BaseModel):
    youtube_url: str
    start_time: str  # Format: "mm:ss" atau "hh:mm:ss"
    end_time: str    # Format: "mm:ss" atau "hh:mm:ss"
    portrait: bool = False
    face_tracking: bool = False
    tracking_sensitivity: int = 5  # 1-10: 1=slow smooth, 10=fast responsive
    callback_url: Optional[str] = None
    
    @field_validator('start_time', 'end_time')
    @classmethod
    def validate_time_format(cls, v):
        if not re.match(r'^(\d{1,2}:)?\d{1,2}:\d{2}(\.\d+)?$', v):
            raise ValueError('Time must be in format mm:ss or hh:mm:ss')
        return v

class ProcessVideoResponse(BaseModel):
    status: str
    job_id: str

@app.post("/process_video", response_model=ProcessVideoResponse)
async def process_video(request: ProcessVideoRequest):
    # Validate time range
    start_seconds = parse_time_to_seconds(request.start_time)
    end_seconds = parse_time_to_seconds(request.end_time)
    
    if end_seconds <= start_seconds:
        raise HTTPException(status_code=400, detail="end_time must be greater than start_time")
    
    job_id = f"job_{uuid.uuid4().hex[:8]}"
    
    job_data = {
        "job_id": job_id,
        "youtube_url": request.youtube_url,
        "start_time": start_seconds,
        "end_time": end_seconds,
        "portrait": request.portrait,
        "face_tracking": request.face_tracking,
        "tracking_sensitivity": min(10, max(1, request.tracking_sensitivity)),
        "callback_url": request.callback_url,
        "status": "pending"
    }
    
    redis_client.lpush("video_jobs", json.dumps(job_data))
    redis_client.set(f"job:{job_id}:status", "pending")
    
    return ProcessVideoResponse(
        status="accepted",
        job_id=job_id
    )


# ==================== CAPTION FEATURE ====================

class CaptionSettings(BaseModel):
    """Settings for caption styling"""
    font_family: str = "Montserrat"
    font_size: int = 60
    line_color: str = "#FFFFFF"
    word_color: str = "#FFDD5C"  # Highlight color for current word
    all_caps: bool = True
    max_words_per_line: int = 3
    bold: bool = True
    italic: bool = False
    underline: bool = False
    strikeout: bool = False
    outline_width: int = 3
    shadow_offset: int = 2
    position: str = "bottom_center"
    style: str = "highlight"  # highlight, karaoke, default

class AddCaptionsRequest(BaseModel):
    """Request to add captions to a video"""
    video_url: str  # URL of the video (MinIO or external)
    language: str = "id"  # Language code for Whisper
    model: str = "medium"  # Whisper model: tiny, base, small, medium, large
    settings: Optional[CaptionSettings] = None
    callback_url: Optional[str] = None

class AddCaptionsResponse(BaseModel):
    status: str
    job_id: str

@app.post("/add_captions", response_model=AddCaptionsResponse)
async def add_captions(request: AddCaptionsRequest):
    """
    Add captions to a video using Whisper transcription
    
    - video_url: URL of the source video
    - language: Language code (default: "id" for Indonesian)
    - settings: Caption styling settings
    """
    job_id = f"caption_{uuid.uuid4().hex[:8]}"
    
    job_data = {
        "job_id": job_id,
        "job_type": "caption",
        "video_url": request.video_url,
        "language": request.language,
        "model": request.model,
        "settings": request.settings.model_dump() if request.settings else {},
        "callback_url": request.callback_url,
        "status": "pending"
    }
    
    redis_client.lpush("caption_jobs", json.dumps(job_data))
    redis_client.set(f"job:{job_id}:status", "pending")
    
    return AddCaptionsResponse(
        status="accepted",
        job_id=job_id
    )


# ==================== TRANSCRIBE YOUTUBE ====================

class TranscribeYoutubeRequest(BaseModel):
    """Request to transcribe a YouTube video"""
    youtube_url: str
    language: str = "id"
    use_whisper: bool = False  # False=YouTube transcript (fast), True=Whisper (accurate)
    model: str = "medium"  # Only used if use_whisper=True
    start_time: Optional[str] = None  # Optional: mm:ss or hh:mm:ss
    end_time: Optional[str] = None    # Optional: mm:ss or hh:mm:ss

class TranscribeYoutubeResponse(BaseModel):
    status: str
    job_id: str

@app.post("/transcribe_youtube", response_model=TranscribeYoutubeResponse)
async def transcribe_youtube(request: TranscribeYoutubeRequest):
    """
    Transcribe a YouTube video and get transcript with timestamps
    
    - youtube_url: YouTube video URL
    - language: Language code (default: "id" for Indonesian)
    - use_whisper: False=use YouTube transcript (fast), True=use Whisper AI (accurate)
    - model: Whisper model, only used if use_whisper=True
    - start_time: Optional start time (mm:ss or hh:mm:ss)
    - end_time: Optional end time (mm:ss or hh:mm:ss)
    """
    job_id = f"transcribe_{uuid.uuid4().hex[:8]}"
    
    # Parse times if provided
    start_seconds = None
    end_seconds = None
    if request.start_time:
        start_seconds = parse_time_to_seconds(request.start_time)
    if request.end_time:
        end_seconds = parse_time_to_seconds(request.end_time)
    
    job_data = {
        "job_id": job_id,
        "job_type": "transcribe_youtube",
        "youtube_url": request.youtube_url,
        "language": request.language,
        "use_whisper": request.use_whisper,
        "model": request.model,
        "start_time": start_seconds,
        "end_time": end_seconds,
        "status": "pending"
    }
    
    redis_client.lpush("transcribe_jobs", json.dumps(job_data))
    redis_client.set(f"job:{job_id}:status", "pending")
    
    return TranscribeYoutubeResponse(
        status="accepted",
        job_id=job_id
    )


@app.get("/job/{job_id}")
async def get_job_status(job_id: str):
    status = redis_client.get(f"job:{job_id}:status")
    if not status:
        raise HTTPException(status_code=404, detail="Job not found")
    
    result = redis_client.get(f"job:{job_id}:result")
    error = redis_client.get(f"job:{job_id}:error")
    
    return {
        "job_id": job_id,
        "status": status.decode(),
        "result": json.loads(result) if result else None,
        "error": error.decode() if error else None
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}