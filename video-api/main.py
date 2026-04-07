from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator, model_validator
from typing import Optional, Dict, Any, List, Union
import uuid
import redis
import json
import os
import re
import time
import asyncio

import yt_dlp
import requests
import logging
import boto3
from youtube_transcript_api import YouTubeTranscriptApi

# Setup Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("uvicorn")

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Video Clipping API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static for presets (simplest way to share JSON between containers if volume mounted)
# or just API endpoints to read/write JSON
PRESETS_FILE = "/app/config/caption_presets.json"
THUMB_PRESETS_FILE = "/app/config/thumbnail_presets.json"

# Ensure config dir
os.makedirs("/app/config", exist_ok=True)

redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))

# --- MinIO Setup ---
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio-storage:9002")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET_NAME = os.getenv("MINIO_BUCKET_NAME", "video-clips")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"

s3_client = boto3.client(
    "s3",
    endpoint_url=f"http://{MINIO_ENDPOINT}" if not MINIO_SECURE else f"https://{MINIO_ENDPOINT}",
    aws_access_key_id=MINIO_ACCESS_KEY,
    aws_secret_access_key=MINIO_SECRET_KEY,
    config=boto3.session.Config(signature_version='s3v4')
)

def upload_to_storage(file_path: str, object_name: str) -> dict:
    """Upload a file to MinIO and return the URL"""
    try:
        s3_client.upload_file(file_path, MINIO_BUCKET_NAME, object_name)
        
        # Construct URL (assuming public or internal access)
        # Note: For internal docker usage, we return the internal URL or a mapped one.
        # Here we return the endpoint URL + bucket + object.
        # If running in docker, MINIO_ENDPOINT is likely internal (minio-storage:9002).
        # Users accessing from host might need localhost mapping, but for n8n/other services internal is fine.
        
        protocol = "https" if MINIO_SECURE else "http"
        url = f"{protocol}://{MINIO_ENDPOINT}/{MINIO_BUCKET_NAME}/{object_name}"
        
        return {"url": url, "bucket": MINIO_BUCKET_NAME, "key": object_name}
    except Exception as e:
        logger.error(f"Failed to upload to storage: {e}")
        raise e

# --- Helper for YT Info ---
def get_video_info_internal(url):
    ydl_opts = {'quiet': True, 'no_warnings': True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            return ydl.extract_info(url, download=False)
        except Exception as e:
            return None

# --- Helper for Transcript ---
def format_transcript(transcript_data):
    formatted_text = []
    seen_lines = set()
    
    if not transcript_data:
        return ""
        
    for item in transcript_data:
        # Handle dict vs object
        if isinstance(item, dict):
             start = float(item.get('start', 0))
             text = item.get('text', '')
        else:
             start = float(getattr(item, 'start', 0))
             text = getattr(item, 'text', '')

        minutes = int(start // 60)
        seconds = int(start % 60)
        text = text.replace('\n', ' ').strip()
        
        if not text: continue
        
        timestamped_line = f"[{minutes:02d}:{seconds:02d}] {text}"
        
        if timestamped_line not in seen_lines:
            formatted_text.append(timestamped_line)
            seen_lines.add(timestamped_line)
            
    return "\n".join(formatted_text)

def fetch_transcript_internal(url):
    try:
        # Extract Video ID
        video_id_match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11}).*', url)
        if not video_id_match:
            return None, "Invalid YouTube URL"
        video_id = video_id_match.group(1)
        
        # Method 1: youtube-transcript-api
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            transcript = None
            try: transcript = transcript_list.find_transcript(['id'])
            except: 
                try: transcript = transcript_list.find_generated_transcript(['id'])
                except:
                     for t in transcript_list:
                         transcript = t
                         break
            
            if transcript:
                transcript_data = transcript.fetch()
                return format_transcript(transcript_data), None
        except Exception:
            pass

        # Method 2: yt-dlp fallback (Manual & Auto-Subs)
        try:
            import yt_dlp
            ydl_opts = {
                'skip_download': True,
                'writesubtitles': True,
                'writeautomaticsub': True,
                'subtitleslangs': ['en', 'id'],
                'quiet': True,
                'noplaylist': True
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                # Check manual subtitles
                subs = info.get('subtitles', {})
                auto_subs = info.get('automatic_captions', {})
                
                selected_sub = None
                
                # Priority: Manual English -> Manual Indo -> Auto English -> Auto Indo
                for lang in ['en', 'id']:
                    if lang in subs:
                        selected_sub = subs[lang]
                        break
                
                if not selected_sub:
                    for lang in ['en', 'id']:
                        if lang in auto_subs:
                            selected_sub = auto_subs[lang]
                            break
                            
                if selected_sub:
                    # selected_sub is list of formats, we need to download one (json3 or vtt)
                    # Actually yt-dlp extract_info doesn't return the content directly if skip_download=True
                    # We might need to fetch the URL provided in 'url' field of the sub format
                    # But often simpler to just use writesubtitles=True and read file?
                    # No, we want in-memory.
                    # Best way: Use 'subtitles' field which contains list of formats. 
                    # Pick 'json3' format and fetch it.
                    
                    sub_url = None
                    for fmt in selected_sub:
                        if fmt.get('ext') == 'json3':
                            sub_url = fmt.get('url')
                            break
                    
                    if not sub_url and selected_sub:
                        # Fallback to any url
                        sub_url = selected_sub[0].get('url')
                        
                    if sub_url:
                        import requests
                        response = requests.get(sub_url)
                        if response.status_code == 200:
                            data = response.json()
                            # Parse json3 format
                            # json3 events: { events: [ { tStartMs: 1000, dDurationMs: 2000, segs: [ { utf8: "text" } ] } ] }
                            if 'events' in data:
                                text_lines = []
                                for event in data['events']:
                                    # Ignore events without segments
                                    if 'segs' not in event: continue
                                    
                                    start_ms = event.get('tStartMs', 0)
                                    text_segs = "".join([s.get('utf8', '') for s in event['segs']])
                                    
                                    minutes = int((start_ms / 1000) // 60)
                                    seconds = int((start_ms / 1000) % 60)
                                    text_lines.append(f"[{minutes:02d}:{seconds:02d}] {text_segs.strip()}")
                                    
                                return "\n".join(text_lines), None
        except Exception as e:
            # logger.error(f"yt-dlp fallback failed: {e}")
            pass

        return None, "NO_TRANSCRIPT_FOUND" # Special code for frontend to handle

    except Exception as e:
        return None, f"Error: {str(e)}"

    except Exception as e:
        return None, str(e)



# ==================== STUDIO API ENDPOINTS ====================

@app.get("/yt/info")
async def get_youtube_info(url: str):
    """Get YouTube video metadata (title, thumbnail, channel)"""
    info = get_video_info_internal(url)
    if not info:
        raise HTTPException(status_code=400, detail="Could not fetch video info")
    
    transcript, _ = fetch_transcript_internal(url)
    
    return {
        "title": info.get('title'),
        "channel": info.get('channel') or info.get('uploader'),
        "thumbnail": info.get('thumbnail'),
        "duration": info.get('duration'),
        "transcript": transcript
    }

@app.get("/presets/thumbnail")
async def get_thumbnail_presets():
    """Get all thumbnail presets"""
    if not os.path.exists(THUMB_PRESETS_FILE):
        return {}
    try:
        with open(THUMB_PRESETS_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

@app.post("/presets/thumbnail")
async def save_thumbnail_preset(name: str, preset: Dict[str, Any]):
    """Save a thumbnail preset"""
    current_presets = {}
    if os.path.exists(THUMB_PRESETS_FILE):
        try:
            with open(THUMB_PRESETS_FILE, 'r') as f:
                current_presets = json.load(f)
        except:
            pass
    
    current_presets[name] = preset
    
    with open(THUMB_PRESETS_FILE, 'w') as f:
        json.dump(current_presets, f, indent=2)
    
    return {"status": "saved", "name": name}

@app.delete("/presets/thumbnail/{name}")
async def delete_thumbnail_preset(name: str):
    """Delete a thumbnail preset"""
    if not os.path.exists(THUMB_PRESETS_FILE):
        return {"status": "not_found"}
        
    try:
        with open(THUMB_PRESETS_FILE, 'r') as f:
            current_presets = json.load(f)
            
        if name in current_presets:
            del current_presets[name]
            with open(THUMB_PRESETS_FILE, 'w') as f:
                json.dump(current_presets, f, indent=2)
            return {"status": "deleted"}
        else:
             raise HTTPException(status_code=404, detail="Preset not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
    split_screen: bool = False
    split_threshold: float = 0.5  # 0.0-1.0: Ratio of secondary/primary score to trigger split
    callback_url: Optional[str] = None
    clip_number: Optional[int] = None  # Passthrough identifier for tracking
    channel_name: Optional[str] = None  # Passthrough
    
    @field_validator('start_time', 'end_time')
    @classmethod
    def validate_time_format(cls, v):
        if not re.match(r'^(\d{1,2}:)?\d{1,2}:\d{2}(\.\d+)?$', v):
            raise ValueError('Time must be in format mm:ss or hh:mm:ss')
        return v

class ProcessVideoResponse(BaseModel):
    status: str
    job_id: str

@app.post("/process_video", response_model=Union[ProcessVideoResponse, Dict[str, Any], List[Any]])
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
        "split_screen": request.split_screen,
        "split_threshold": request.split_threshold,
        "callback_url": request.callback_url,
        "clip_number": request.clip_number,
        "channel_name": request.channel_name,
        "status": "pending"
    }
    
    redis_client.lpush("video_jobs", json.dumps(job_data))
    redis_client.set(f"job:{job_id}:status", "pending")
    
    # If callback provided, return async response
    if request.callback_url:
        return ProcessVideoResponse(
            status="accepted",
            job_id=job_id
        )
        
    # If no callback, wait for result (Synchronous Mode)
    # Poll Redis for completion
    timeout = 600  # 10 minutes timeout
    start_wait = time.time()
    
    while (time.time() - start_wait) < timeout:
        status = redis_client.get(f"job:{job_id}:status")
        if status:
            status = status.decode('utf-8')
            
        if status == "completed":
            result_json = redis_client.get(f"job:{job_id}:result")
            if result_json:
                result = json.loads(result_json)
                return result
            else:
                raise HTTPException(status_code=500, detail="Job completed but no result found")
                
        elif status == "failed":
            error_msg = redis_client.get(f"job:{job_id}:error")
            if error_msg:
                error_msg = error_msg.decode('utf-8')
            raise HTTPException(status_code=500, detail=f"Job failed: {error_msg}")
            
        await asyncio.sleep(1) # Wait 1 second before next check
        
    raise HTTPException(status_code=504, detail="Job timed out")


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
    outline_color: str = "#000000"
    shadow_offset: int = 2
    margin_v: int = 640
    position: str = "bottom_center"
    style: str = "highlight"  # highlight, karaoke, default

class AddCaptionsRequest(BaseModel):
    """Request to add captions to a video"""
    video_url: str  # URL of the video (MinIO or external)
    language: str = "id"  # Language code for Whisper
    model: str = "medium"  # Whisper model: tiny, base, small, medium, large
    settings: Optional[CaptionSettings] = None
    callback_url: Optional[str] = None
    callback_url: Optional[str] = None
    capt_number: Optional[int] = None  # Passthrough identifier for tracking

class AddCaptionsResponse(BaseModel):
    status: str
    job_id: str

@app.post("/add_captions", response_model=Union[AddCaptionsResponse, Dict[str, Any], List[Any]])
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
        "capt_number": request.capt_number,
        "status": "pending"
    }
    
    redis_client.lpush("caption_jobs", json.dumps(job_data))
    redis_client.set(f"job:{job_id}:status", "pending")
    
    # If callback provided, return async response
    if request.callback_url:
        return AddCaptionsResponse(
            status="accepted",
            job_id=job_id
        )
        
    # If no callback, wait for result (Synchronous Mode)
    # Poll Redis for completion
    timeout = 600  # 10 minutes timeout
    start_wait = time.time()
    
    while (time.time() - start_wait) < timeout:
        status = redis_client.get(f"job:{job_id}:status")
        if status:
            status = status.decode('utf-8')
            
        if status == "completed":
            result_json = redis_client.get(f"job:{job_id}:result")
            if result_json:
                result = json.loads(result_json)
                return result
            else:
                raise HTTPException(status_code=500, detail="Job completed but no result found")
                
        elif status == "failed":
            error_msg = redis_client.get(f"job:{job_id}:error")
            if error_msg:
                error_msg = error_msg.decode('utf-8')
            raise HTTPException(status_code=500, detail=f"Job failed: {error_msg}")
            
        await asyncio.sleep(1) # Wait 1 second before next check
        
    raise HTTPException(status_code=504, detail="Job timed out")


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

@app.post("/generate_thumbnail", response_model=Union[ThumbnailResponse, Dict[str, Any], List[Any]])
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
    
    # If callback provided, return async response
    if request.callback_url:
        return ThumbnailResponse(
            status="accepted",
            job_id=job_id
        )
        
    # If no callback, wait for result (Synchronous Mode)
    # Poll Redis for completion
    timeout = 600  # 10 minutes timeout
    start_wait = time.time()
    
    while (time.time() - start_wait) < timeout:
        status = redis_client.get(f"job:{job_id}:status")
        if status:
            status = status.decode('utf-8')
            
        if status == "completed":
            result_json = redis_client.get(f"job:{job_id}:result")
            if result_json:
                result = json.loads(result_json)
                return result
            else:
                raise HTTPException(status_code=500, detail="Job completed but no result found")
                
        elif status == "failed":
            error_msg = redis_client.get(f"job:{job_id}:error")
            if error_msg:
                error_msg = error_msg.decode('utf-8')
            raise HTTPException(status_code=500, detail=f"Job failed: {error_msg}")
            
        await asyncio.sleep(1) # Wait 1 second before next check
        
    raise HTTPException(status_code=504, detail="Job timed out")


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


# (Section removed: Duplicate async video source endpoint)


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

@app.post("/add_image_watermark")
async def add_image_watermark(request: AddImageWatermarkRequest):
    """
    Add image watermark to a video (Synchronous)
    
    - video_url: URL of the source video
    - image_url: URL of watermark image (PNG with transparency recommended)
    - size: Resize options (width, height, or scale)
    - position: Position on video (7 options available)
    - opacity: Transparency level (0.0 - 1.0)
    """
    job_id = f"imgwm_{uuid.uuid4().hex[:8]}"
    start_ts = time.time()
    
    try:
        # Convert models to dicts
        size_dict = request.size.model_dump() if request.size else {}
        position_dict = request.position.model_dump() if request.position else {}
        
        # Execute synchronously
        result = add_image_watermark_to_video(
            video_url=request.video_url,
            image_url=request.image_url,
            job_id=job_id,
            size=size_dict,
            position=position_dict,
            opacity=request.opacity
        )
        
        # Upload to MinIO
        video_path = result["output_path"]
        filename = os.path.basename(video_path)
        upload_result = upload_to_storage(video_path, filename)
        
        # Cleanup
        if os.path.exists(video_path):
            os.remove(video_path)
            
        total_time = time.time() - start_ts
        
        return [
            {
                "build_number": 1, 
                "code": 200,
                "endpoint": "/add_image_watermark",
                "id": None,
                "job_id": job_id,
                "message": "success",
                "pid": os.getpid(),
                "queue_id": 0,
                "queue_length": 0,
                "queue_time": 0,
                "response": upload_result["url"],
                "run_time": round(total_time, 3), 
                "total_time": round(total_time, 3)
            }
        ]
        
    except Exception as e:
        logger.error(f"Add Image Watermark failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== VIDEO MERGE FEATURE ====================

class VideoInput(BaseModel):
    """Single video input for merge"""
    video_url: str

class MergeVideosRequest(BaseModel):
    """Request to merge multiple videos"""
    videos: List[VideoInput]  # List of videos to merge (in order)
    callback_url: Optional[str] = None

@app.post("/merge_videos")
async def merge_videos(request: MergeVideosRequest):
    """
    Merge multiple videos into one (Synchronous)
    
    - videos: List of video URLs to merge (in order)
    - Videos will be concatenated sequentially
    """
    if len(request.videos) < 2:
        raise HTTPException(status_code=400, detail="At least 2 videos are required to merge")
    
    job_id = f"merge_{uuid.uuid4().hex[:8]}"
    start_ts = time.time()
    
    try:
        # Execute synchronously
        result = merge_videos_module(
            video_urls=[v.video_url for v in request.videos],
            job_id=job_id
        )
        
        # Upload to MinIO
        video_path = result["output_path"]
        filename = os.path.basename(video_path)
        upload_result = upload_to_storage(video_path, filename)
        
        # Cleanup
        if os.path.exists(video_path):
            os.remove(video_path)
            
        total_time = time.time() - start_ts
        
        return [
            {
                "build_number": 1, 
                "code": 200,
                "endpoint": "/merge_videos",
                "id": None,
                "job_id": job_id,
                "message": "success",
                "pid": os.getpid(),
                "queue_id": 0,
                "queue_length": 0,
                "queue_time": 0,
                "response": upload_result["url"],
                "run_time": round(total_time, 3), 
                "total_time": round(total_time, 3)
            }
        ]
        
    except Exception as e:
        logger.error(f"Merge Videos failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== OVERLAY NOTIFICATION FEATURE ====================

class OverlayResize(BaseModel):
    """Resize options for overlay video"""
    width: Optional[int] = None
    height: Optional[int] = None
    scale: Optional[float] = None # e.g. 0.5 for 50% size

class OverlayChromaKey(BaseModel):
    """Chroma key settings"""
    color: Optional[str] = None # Hex color #00FF00. If None, auto-detect.
    similarity: float = 0.3 # 0.0-1.0
    blend: float = 0.1 # 0.0-1.0
    auto: bool = True # Enable auto-detection
    crop: bool = True # Enable smart auto-crop

class OverlayPosition(BaseModel):
    """Position options"""
    preset: Optional[str] = "bottom_right" # top_left, top_right, bottom_left, bottom_right, center
    x: Optional[str] = None # FFmpeg expression if custom
    y: Optional[str] = None # FFmpeg expression if custom
    margin_x: int = 30
    margin_y: int = 30

class OverlayNotificationRequest(BaseModel):
    """Request to add overlay notification (e.g. Subscribe button)"""
    video_url: str
    overlay_url: str
    start_time: str = "00:00" # "MM:SS"
    position: Optional[OverlayPosition] = None
    resize: Optional[OverlayResize] = None
    chroma_key: Optional[OverlayChromaKey] = None
    callback_url: Optional[str] = None

@app.post("/overlay_notification")
async def overlay_notification(request: OverlayNotificationRequest):
    """
    Add a video overlay (e.g. Subscribe animation) with Chroma Key background removal.
    
    - video_url: Main video
    - overlay_url: Overlay video (e.g. green screen)
    - start_time: When to show overlay (MM:SS)
    - chroma_key: Auto-detect background color or specify manually
    """
    job_id = f"ovly_{uuid.uuid4().hex[:8]}"
    
    # Defaults
    position = request.position.model_dump() if request.position else {"preset": "bottom_right"}
    resize = request.resize.model_dump() if request.resize else {}
    chroma_key = request.chroma_key.model_dump() if request.chroma_key else {"auto": True}
    
    job_data = {
        "job_id": job_id,
        "job_type": "overlay_notification",
        "video_url": request.video_url,
        "overlay_url": request.overlay_url,
        "start_time": request.start_time,
        "position": position,
        "resize": resize,
        "chroma_key": chroma_key,
        "callback_url": request.callback_url,
        "status": "pending"
    }
    
    redis_client.lpush("overlay_notification_jobs", json.dumps(job_data))
    redis_client.set(f"job:{job_id}:status", "pending")
    
    # If callback provided, return async
    if request.callback_url:
        return {"status": "accepted", "job_id": job_id}
        
    # Synchronous Poll (similar to other endpoints)
    timeout = 600
    start_wait = time.time()
    
    while (time.time() - start_wait) < timeout:
        status = redis_client.get(f"job:{job_id}:status")
        if status:
            status = status.decode('utf-8')
            
        if status == "completed":
            result_json = redis_client.get(f"job:{job_id}:result")
            if result_json:
                return json.loads(result_json)
        elif status == "failed":
            error_msg = redis_client.get(f"job:{job_id}:error")
            raise HTTPException(status_code=500, detail=f"Job failed: {error_msg.decode('utf-8') if error_msg else 'Unknown error'}")
            
        await asyncio.sleep(1)
        
    raise HTTPException(status_code=504, detail="Job timed out")

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
    url: Optional[str] = None

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
    
    try:
        # 1. Create Video Synchronously
        # Convert request.images to list of dicts as expected by the module
        images_data = [{"image_url": img.image_url, "duration": img.duration} for img in request.images]
        
        result = create_video_from_images(
            images=images_data,
            job_id=job_id,
            fps=request.fps,
            transition=request.transition,
            motion=request.motion,
            motion_intensity=request.motion_intensity
        )
        
        video_path = result["output_path"]
        
        # 2. Upload to MinIO
        filename = os.path.basename(video_path)
        upload_result = upload_to_storage(video_path, filename)
        
        # 3. Cleanup local file (API container storage is ephemeral/shared)
        if os.path.exists(video_path):
            os.remove(video_path)
            
        return ImageToVideoResponse(
            status="success",
            job_id=job_id,
            url=upload_result["url"]
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
# ==================== MEDIA INFO FEATURE ====================

from modules.media_metadata import get_ffprobe_info
from modules.image_to_video import create_video_from_images
from modules.exporter import upload_to_storage

class MediaInfoRequest(BaseModel):
    url: Optional[str] = None
    media_url: Optional[str] = None

    @model_validator(mode='after')
    def check_url(self):
        if not self.url and self.media_url:
            self.url = self.media_url
        
        if not self.url:
            raise ValueError("Either 'url' or 'media_url' is required")
        return self

class MediaInfoResponse(BaseModel):
    status: str
    type: str  # video, audio, image, etc.
    source: str # youtube, direct
    metadata: Dict[str, Any]

@app.post("/media_info", response_model=MediaInfoResponse)
async def get_media_info(request: MediaInfoRequest):
    """
    Get detailed metadata for a media URL (Video, Audio, Image)
    """
    url = request.url
    
    # Check if YouTube
    if "youtube.com" in url or "youtu.be" in url:
        info = get_video_info_internal(url)
        if not info:
             raise HTTPException(status_code=400, detail="Could not fetch YouTube info")
        
        # Normalize YouTube info to match common structure
        return MediaInfoResponse(
            status="success",
            type="video",
            source="youtube",
            metadata={
                "title": info.get("title"),
                "channel": info.get("uploader"),
                "duration": info.get("duration"),
                "width": info.get("width"),
                "height": info.get("height"),
                "thumbnail": info.get("thumbnail"),
                "view_count": info.get("view_count"),
                "resolution": info.get("resolution") or f"{info.get('width')}x{info.get('height')}"
            }
        )
    
    # Direct File (via FFprobe)
    # Using helper from modules
    info = get_ffprobe_info(url)
    if info:
        return MediaInfoResponse(
            status="success",
            type=info["type"],
            source="direct",
            metadata=info["metadata"]
        )
        
    raise HTTPException(status_code=400, detail="Could not fetch media info")

# ==================== TRIM FEATURE ====================

from modules.trimmer import trim_video

class TrimRequest(BaseModel):
    video_url: str
    start: str  # "00:00:00" or seconds
    end: str    # "00:00:05.00" or seconds
    video_codec: str = "libx264"
    video_preset: str = "faster"
    video_crf: int = 28
    audio_codec: str = "aac"
    audio_bitrate: str = "128k"
    webhook_url: Optional[str] = None
    id: Optional[str] = None

@app.post("/trim")
async def trim_video_endpoint(request: TrimRequest):
    """
    Synchronous video trimming endpoint
    """
    job_id = f"{uuid.uuid4()}"
    start_ts = time.time()
    
    try:
        # Execute trim synchronously
        result = trim_video(
            video_url=request.video_url,
            job_id=job_id,
            start_time=request.start,
            end_time=request.end,
            video_codec=request.video_codec,
            video_preset=request.video_preset,
            video_crf=request.video_crf,
            audio_codec=request.audio_codec,
            audio_bitrate=request.audio_bitrate
        )
        
        # Upload to MinIO
        video_path = result["output_path"]
        filename = f"{job_id}_output.mp4"
        upload_result = upload_to_storage(video_path, filename)
        
        # Cleanup
        if os.path.exists(video_path):
            os.remove(video_path)
            
        total_time = time.time() - start_ts
        
        # Return exact format requested
        return [
            {
                "build_number": 1, # Static or env var
                "code": 200,
                "endpoint": "/v1/video/trim", # mimicking requested path
                "id": request.id,
                "job_id": job_id,
                "message": "success",
                "pid": os.getpid(),
                "queue_id": 0, # N/A for sync
                "queue_length": 0,
                "queue_time": 0,
                "response": upload_result["url"],
                "run_time": round(result["run_time"], 3),
                "total_time": round(total_time, 3)
            }
        ]
        
    except Exception as e:
        logger.error(f"Trim failed: {str(e)}")
        # Construct error response to match successful structure but with error info?
        # User only showed success example. Raising standard HTTP exception for now.
        raise HTTPException(status_code=500, detail=str(e))


# ==================== COMPOSER FEATURE ====================

from modules.composer import compose_video

class InputFile(BaseModel):
    url: Optional[str] = None
    file_url: Optional[str] = None
    input_name: Optional[str] = None
    options: List[str] = []

    @model_validator(mode='after')
    def check_url(self):
        if not self.url and self.file_url:
            self.url = self.file_url
        if not self.url:
            raise ValueError("url or file_url is required")
        return self

class OutputOption(BaseModel):
    option: str
    argument: Optional[str] = None

class OutputSpec(BaseModel):
    options: List[OutputOption]

class ComposeRequest(BaseModel):
    inputs: List[InputFile]
    filter_complex: Optional[str] = None
    output_args: Optional[List[str]] = None
    outputs: Optional[List[OutputSpec]] = None # Support user's nested structure
    output_format: str = "mp4"
    webhook_url: Optional[str] = None
    id: Optional[str] = None

@app.post("/compose")
async def compose_video_endpoint(request: ComposeRequest):
    """
    Synchronous video composer endpoint for complex FFmpeg commands
    """
    job_id = f"compose_{uuid.uuid4().hex[:8]}"
    start_ts = time.time()
    
    try:
        # Normalize inputs
        inputs_data = []
        for inp in request.inputs:
            d = inp.model_dump()
            d['url'] = inp.url # Ensure url is populated from logic
            inputs_data.append(d)
            
        # Normalize output_args from "outputs" if present
        final_output_args = request.output_args or []
        if request.outputs:
            for out in request.outputs:
                for opt in out.options:
                    final_output_args.append(opt.option)
                    if opt.argument:
                        final_output_args.append(opt.argument)

        # Execute compose synchronously
        result = compose_video(
            job_id=job_id,
            inputs=inputs_data,
            filter_complex=request.filter_complex,
            output_args=final_output_args,
            output_format=request.output_format
        )
        
        # Upload to MinIO
        video_path = result["output_path"]
        filename = os.path.basename(video_path)
        upload_result = upload_to_storage(video_path, filename)
        
        # Cleanup
        if os.path.exists(video_path):
            os.remove(video_path)
            
        total_time = time.time() - start_ts
        
        return [
            {
                "build_number": 1, 
                "code": 200,
                "endpoint": "/v1/video/compose",
                "id": request.id,
                "job_id": job_id,
                "message": "success",
                "pid": os.getpid(),
                "queue_id": 0,
                "queue_length": 0,
                "queue_time": 0,
                "response": upload_result["url"],
                "run_time": round(result["run_time"], 3),
                "total_time": round(total_time, 3)
            }
        ]
        
    except Exception as e:
        logger.error(f"Compose failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== VIDEO SOURCE FEATURE ====================

from modules.video_source import add_video_source_to_video
from modules.image_watermark import add_image_watermark_to_video
from modules.video_merge import merge_videos as merge_videos_module

class TextStyle(BaseModel):
    font_family: Optional[str] = "Montserrat"
    font_size: Optional[int] = 40
    color: Optional[str] = "#FFFFFF"
    bold: Optional[bool] = True
    italic: Optional[bool] = False
    stroke_color: Optional[str] = "#000000"
    stroke_width: Optional[int] = 0

class PositionStyle(BaseModel):
    position: Optional[str] = "bottom_right"
    margin_x: Optional[Union[int, str]] = 30
    margin_y: Optional[Union[int, str]] = 30

class VideoSourceRequest(BaseModel):
    video_url: str
    channel_name: str
    prefix: Optional[str] = "FullVideo:"
    prefix_style: Optional[TextStyle] = None
    channel_style: Optional[TextStyle] = None
    position: Optional[PositionStyle] = None
    webhook_url: Optional[str] = None
    id: Optional[str] = None
    logo_url: Optional[str] = None  # New: URL for logo image
    logo_scale: float = 1.0         # New: Scale relative to text block height
    line_spacing: int = 8           # New: Vertical spacing between prefix and channel
    logo_offset_y: int = 0          # New: Vertical offset for logo adjustment
    logo_spacing: int = 10          # New: Horizontal spacing between logo and text

@app.post("/add_video_source")
async def add_video_source(request: VideoSourceRequest):
    """
    Add video source overlay to a video
    """
    logger.info(f"Received add_video_source request: video_url='{request.video_url}', channel='{request.channel_name}'")
    
    if not request.video_url:
        raise HTTPException(status_code=400, detail="video_url cannot be empty")

    job_id = f"vsrc_{uuid.uuid4().hex[:8]}"
    start_ts = time.time()
    
    try:
        # Convert models to dicts
        prefix_style_dict = request.prefix_style.model_dump() if request.prefix_style else {}
        channel_style_dict = request.channel_style.model_dump() if request.channel_style else {}
        position_dict = request.position.model_dump() if request.position else {}
        
        # Execute synchronously
        result = add_video_source_to_video(
            video_url=request.video_url,
            job_id=job_id,
            channel_name=request.channel_name,
            prefix=request.prefix,
            prefix_style=prefix_style_dict,
            channel_style=channel_style_dict,
            position=position_dict,
            logo_url=request.logo_url,
            logo_scale=request.logo_scale,
            line_spacing=request.line_spacing,
            logo_offset_y=request.logo_offset_y,
            logo_spacing=request.logo_spacing
        )
        
        # Upload to MinIO
        video_path = result["output_path"]
        filename = os.path.basename(video_path)
        upload_result = upload_to_storage(video_path, filename)
        
        # Cleanup
        if os.path.exists(video_path):
            os.remove(video_path)
            
        total_time = time.time() - start_ts
        
        return [
            {
                "build_number": 1, 
                "code": 200,
                "endpoint": "/add_video_source",
                "id": request.id,
                "job_id": job_id,
                "message": "success",
                "pid": os.getpid(),
                "queue_id": 0,
                "queue_length": 0,
                "queue_time": 0,
                "response": upload_result["url"],
                "run_time": round(total_time, 3), 
                "total_time": round(total_time, 3)
            }
        ]
        
    except Exception as e:
        logger.error(f"Add Video Source failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))