from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, field_validator
from typing import Optional, Dict, Any, List
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
    camera_smoothing: float = 0.25  # 0.05-0.5: Higher = faster camera movement
    zoom_threshold: float = 20.0  # 8.0-30.0: Lip activity threshold (Higher = only laugh/surprise)
    zoom_level: float = 1.15      # 1.0-1.5: Target zoom factor (1.15 = 15% zoom)
    callback_url: Optional[str] = None
    clip_number: Optional[int] = None  # Passthrough identifier for tracking
    
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
        "camera_smoothing": min(0.5, max(0.05, request.camera_smoothing)),
        "zoom_threshold": request.zoom_threshold,
        "zoom_level": request.zoom_level,
        "callback_url": request.callback_url,
        "clip_number": request.clip_number,
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
    caps_number: Optional[int] = None  # Passthrough identifier for tracking

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
        "caps_number": request.caps_number,
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


# ==================== THUMBNAIL FEATURE ====================

class FrameSelection(BaseModel):
    mode: str = "face_detection"  # face_detection, timestamp
    timestamp: Optional[str] = None
    prefer: str = "centered"  # centered, largest, most_active

class BackgroundImage(BaseModel):
    url: str
    fit: str = "cover"  # cover, contain, fill

class TextStyle(BaseModel):
    font_family: str = "Montserrat"
    font_weight: str = "bold"
    font_size: int = 100
    color: str = "#FFFFFF"
    text_transform: Optional[str] = None  # uppercase, lowercase, capitalize
    text_shadow: Optional[str] = None  # e.g. "2px 2px 4px #000000"
    stroke_color: Optional[str] = None
    stroke_width: int = 0
    align: str = "center"
    line_height: Optional[float] = None  # Multiplier e.g. 1.2 = 120% of font size
    line_spacing: Optional[int] = None  # Pixel value (overrides line_height if set)
    letter_spacing: Optional[int] = None  # Extra pixels between characters

class TextBackground(BaseModel):
    enabled: bool = True
    color: str = "rgba(0, 0, 0, 0.7)"
    padding: int = 40
    radius: int = 20
    full_width: bool = True
    gradient: bool = False  # Enable gradient from bottom (solid) to top (transparent)
    gradient_height: int = 0  # Custom height, 0 = auto (extends above text)

class TextPosition(BaseModel):
    x: str = "center"  # left, center, right, or pixel
    y: str = "bottom"  # top, center, bottom, or pixel
    margin_top: int = 0
    margin_bottom: int = 250  # Higher default
    margin_left: int = 0
    margin_right: int = 0
    edge_padding: int = 40  # Minimum padding from frame edges
    max_lines: int = 3  # Maximum number of text lines (truncate with ... if exceeded)

class TextOverlay(BaseModel):
    text: str
    style: Optional[TextStyle] = None
    background: Optional[TextBackground] = None
    position: Optional[TextPosition] = None

class ExportSettings(BaseModel):
    format: str = "png"  # png, jpg, webp
    quality: int = 95

class ThumbnailRequest(BaseModel):
    video_url: Optional[str] = None
    frame_selection: Optional[FrameSelection] = None
    size: str = "1080x1920"
    background_image: Optional[BackgroundImage] = None
    text_overlay: TextOverlay
    export: Optional[ExportSettings] = None
    callback_url: Optional[str] = None
    thumbnail_number: Optional[int] = None  # Passthrough identifier for tracking

class ThumbnailResponse(BaseModel):
    status: str
    job_id: str

@app.post("/generate_thumbnail", response_model=ThumbnailResponse)
async def generate_thumbnail(request: ThumbnailRequest):
    """Generate thumbnail from video with face detection and text overlay."""
    
    if not request.video_url and not request.background_image:
        raise HTTPException(
            status_code=400, 
            detail="Either video_url or background_image is required"
        )
    
    job_id = f"thumb_{uuid.uuid4().hex[:8]}"
    
    job_data = {
        "job_id": job_id,
        "job_type": "thumbnail",
        "video_url": request.video_url,
        "frame_selection": request.frame_selection.model_dump() if request.frame_selection else None,
        "size": request.size,
        "background_image": request.background_image.model_dump() if request.background_image else None,
        "text_overlay": {
            "text": request.text_overlay.text,
            "style": (request.text_overlay.style.model_dump() if request.text_overlay.style 
                     else TextStyle().model_dump()),
            "background": (request.text_overlay.background.model_dump() if request.text_overlay.background 
                          else TextBackground().model_dump()),
            "position": (request.text_overlay.position.model_dump() if request.text_overlay.position 
                        else TextPosition().model_dump()),
        },
        "export": (request.export.model_dump() if request.export 
                  else ExportSettings().model_dump()),
        "callback_url": request.callback_url,
        "thumbnail_number": request.thumbnail_number,
        "status": "pending"
    }
    
    redis_client.lpush("thumbnail_jobs", json.dumps(job_data))
    redis_client.set(f"job:{job_id}:status", "pending")
    
    return ThumbnailResponse(
        status="accepted",
        job_id=job_id
    )


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


# ==================== VIDEO SOURCE OVERLAY FEATURE ====================

class VideoSourceTextStyle(BaseModel):
    """Text styling options for video source overlay"""
    font_family: str = "Montserrat"
    font_size: int = 40
    color: str = "#FFFFFF"
    bold: bool = True
    italic: bool = False

class VideoSourceBackground(BaseModel):
    """Background overlay options for video source text"""
    enabled: bool = True
    color: str = "rgba(0, 0, 0, 0.5)"
    padding: int = 20
    radius: int = 10

class VideoSourcePosition(BaseModel):
    """Position options for video source overlay"""
    position: str = "bottom_right"  # top_left, top_right, bottom_left, bottom_right
    margin_x: int = 30
    margin_y: int = 30

class AddVideoSourceRequest(BaseModel):
    """Request to add video source overlay to a video"""
    video_url: str
    channel_name: str  # e.g. "MyYoutube Channel"
    prefix: str = "FullVideo:"  # Text before channel name
    text_style: Optional[VideoSourceTextStyle] = None
    background: Optional[VideoSourceBackground] = None
    position: Optional[VideoSourcePosition] = None
    callback_url: Optional[str] = None

class AddVideoSourceResponse(BaseModel):
    status: str
    job_id: str

@app.post("/add_video_source", response_model=AddVideoSourceResponse)
async def add_video_source(request: AddVideoSourceRequest):
    """
    Add video source overlay to a video
    
    - video_url: URL of the source video
    - channel_name: Channel name to display (e.g. "MyYoutube Channel")
    - prefix: Text before channel name (default: "FullVideo:")
    - text_style: Text styling options
    - background: Background overlay options
    - position: Position on video
    """
    job_id = f"vsource_{uuid.uuid4().hex[:8]}"
    
    job_data = {
        "job_id": job_id,
        "job_type": "video_source",
        "video_url": request.video_url,
        "channel_name": request.channel_name,
        "prefix": request.prefix,
        "text_style": request.text_style.model_dump() if request.text_style else VideoSourceTextStyle().model_dump(),
        "background": request.background.model_dump() if request.background else VideoSourceBackground().model_dump(),
        "position": request.position.model_dump() if request.position else VideoSourcePosition().model_dump(),
        "callback_url": request.callback_url,
        "status": "pending"
    }
    
    redis_client.lpush("video_source_jobs", json.dumps(job_data))
    redis_client.set(f"job:{job_id}:status", "pending")
    
    return AddVideoSourceResponse(
        status="accepted",
        job_id=job_id
    )


# ==================== IMAGE WATERMARK FEATURE ====================

class ImageWatermarkSize(BaseModel):
    """Size options for watermark image"""
    width: Optional[int] = None   # Target width in pixels
    height: Optional[int] = None  # Target height in pixels
    scale: Optional[float] = None # Scale factor (e.g. 0.5 = 50%)

class ImageWatermarkPosition(BaseModel):
    """Position options for watermark"""
    position: str = "bottom_right"  # top_left, top_center, top_right, center, bottom_left, bottom_center, bottom_right
    margin_x: int = 30
    margin_y: int = 30

class AddImageWatermarkRequest(BaseModel):
    """Request to add image watermark to a video"""
    video_url: str
    image_url: str  # URL of watermark image (PNG recommended for transparency)
    size: Optional[ImageWatermarkSize] = None
    position: Optional[ImageWatermarkPosition] = None
    opacity: float = 1.0  # 0.0 - 1.0
    callback_url: Optional[str] = None

class AddImageWatermarkResponse(BaseModel):
    status: str
    job_id: str

@app.post("/add_image_watermark", response_model=AddImageWatermarkResponse)
async def add_image_watermark(request: AddImageWatermarkRequest):
    """
    Add image watermark to a video
    
    - video_url: URL of the source video
    - image_url: URL of watermark image (PNG with transparency recommended)
    - size: Resize options (width, height, or scale)
    - position: Position on video (7 options available)
    - opacity: Transparency level (0.0 - 1.0)
    """
    job_id = f"imgwm_{uuid.uuid4().hex[:8]}"
    
    job_data = {
        "job_id": job_id,
        "job_type": "image_watermark",
        "video_url": request.video_url,
        "image_url": request.image_url,
        "size": request.size.model_dump() if request.size else {},
        "position": request.position.model_dump() if request.position else ImageWatermarkPosition().model_dump(),
        "opacity": min(1.0, max(0.0, request.opacity)),
        "callback_url": request.callback_url,
        "status": "pending"
    }
    
    redis_client.lpush("image_watermark_jobs", json.dumps(job_data))
    redis_client.set(f"job:{job_id}:status", "pending")
    
    return AddImageWatermarkResponse(
        status="accepted",
        job_id=job_id
    )


# ==================== VIDEO MERGE FEATURE ====================

class VideoInput(BaseModel):
    """Single video input for merge"""
    video_url: str

class MergeVideosRequest(BaseModel):
    """Request to merge multiple videos"""
    videos: List[VideoInput]  # List of videos to merge (in order)
    callback_url: Optional[str] = None

class MergeVideosResponse(BaseModel):
    status: str
    job_id: str

@app.post("/merge_videos", response_model=MergeVideosResponse)
async def merge_videos(request: MergeVideosRequest):
    """
    Merge multiple videos into one
    
    - videos: List of video URLs to merge (in order)
    - Videos will be concatenated sequentially
    """
    if len(request.videos) < 2:
        raise HTTPException(status_code=400, detail="At least 2 videos are required to merge")
    
    job_id = f"merge_{uuid.uuid4().hex[:8]}"
    
    job_data = {
        "job_id": job_id,
        "job_type": "merge_videos",
        "videos": [v.video_url for v in request.videos],
        "callback_url": request.callback_url,
        "status": "pending"
    }
    
    redis_client.lpush("merge_videos_jobs", json.dumps(job_data))
    redis_client.set(f"job:{job_id}:status", "pending")
    
    return MergeVideosResponse(
        status="accepted",
        job_id=job_id
    )


# ==================== IMAGE TO VIDEO FEATURE ====================

class ImageInputItem(BaseModel):
    """Single image input for video creation"""
    image_url: str
    duration: float = 3.0  # Seconds to show this image

class ImageToVideoRequest(BaseModel):
    """Request to create video from images"""
    images: List[ImageInputItem]
    fps: int = 30
    transition: Optional[str] = None  # fade, wipeleft, slideright, etc
    motion: Optional[str] = None  # zoom_in, zoom_out, pan_left, pan_right, pan_up, pan_down
    motion_intensity: float = 0.3  # 0.1 (subtle) to 1.0 (strong), default 0.3 = 30% zoom
    callback_url: Optional[str] = None

class ImageToVideoResponse(BaseModel):
    status: str
    job_id: str

@app.post("/image_to_video", response_model=ImageToVideoResponse)
async def image_to_video(request: ImageToVideoRequest):
    """
    Create video from images
    
    - images: List of images with duration (seconds)
    - fps: Frames per second (default 30)
    - transition: Optional transition effect (fade, wipeleft, etc)
    - motion: Optional motion effect (zoom_in, zoom_out, pan_left, pan_right)
    - motion_intensity: Zoom/pan intensity 0.1-1.0 (default 0.3)
    """
    if len(request.images) < 1:
        raise HTTPException(status_code=400, detail="At least 1 image is required")
    
    job_id = f"img2vid_{uuid.uuid4().hex[:8]}"
    
    job_data = {
        "job_id": job_id,
        "job_type": "image_to_video",
        "images": [{"image_url": img.image_url, "duration": img.duration} for img in request.images],
        "fps": request.fps,
        "transition": request.transition,
        "motion": request.motion,
        "motion_intensity": request.motion_intensity,
        "callback_url": request.callback_url,
        "status": "pending"
    }
    
    redis_client.lpush("image_to_video_jobs", json.dumps(job_data))
    redis_client.set(f"job:{job_id}:status", "pending")
    
    return ImageToVideoResponse(
        status="accepted",
        job_id=job_id
    )