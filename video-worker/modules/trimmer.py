"""
Video Trimmer Module
Handles video trimming operations using FFmpeg.
"""

import subprocess
import os
import logging
import time
import requests
import re
from typing import Optional

logger = logging.getLogger(__name__)

def download_file(url: str, output_path: str) -> str:
    """Download file from URL to local path (Reused from image_to_video.py)"""
    internal_url = url
    
    # Handle hostname conflicts
    internal_url = re.sub(r'http://minio:9000/', 'http://minio-nca:9000/', internal_url)
    internal_url = re.sub(r'http://localhost:9000/', 'http://minio-nca:9000/', internal_url)
    
    # Handle new minio-storage endpoint (port 9002)
    internal_url = re.sub(r'http://localhost:9002/', 'http://minio-storage:9002/', internal_url)
    internal_url = re.sub(r'http://127.0.0.1:9002/', 'http://minio-storage:9002/', internal_url)
    internal_url = internal_url.replace("minio_storage", "minio-storage")
    
    # Handle misconfigured n8n URL
    internal_url = re.sub(r'http://n8n-ncat:5678/', 'http://minio-storage:9002/', internal_url)
    internal_url = internal_url.replace("http://minio:9002/", "http://minio-storage:9002/")
    internal_url = internal_url.replace("minio-video", "minio-storage")
    
    logger.info(f"Downloading: {internal_url}")
    
    response = requests.get(internal_url, stream=True, timeout=120)
    response.raise_for_status()
    
    with open(output_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
            
    return output_path

def trim_video(
    video_url: str,
    job_id: str,
    start_time: str,
    end_time: str,
    video_codec: str = "libx264",
    video_preset: str = "faster",
    video_crf: int = 23,
    audio_codec: str = "aac",
    audio_bitrate: str = "128k"
) -> dict:
    """
    Trim video based on start and end times.
    
    Args:
        video_url: Source video URL
        job_id: Unique job identifier
        start_time: Start time (HH:MM:SS or seconds)
        end_time: End time (HH:MM:SS or seconds)
        video_codec: Video codec (default: libx264)
        video_preset: Encoding preset (default: faster)
        video_crf: CRF quality value (default: 23)
        audio_codec: Audio codec (default: aac)
        audio_bitrate: Audio bitrate (default: 128k)
        
    Returns:
        dict: {
            "output_path": str,
            "run_time": float
        }
    """
    start_ts = time.time()
    
    input_path = f"/app/output/{job_id}_input.mp4"
    output_path = f"/app/output/{job_id}_output.mp4"
    
    try:
        # 1. Download source
        download_file(video_url, input_path)
        
        # 2. Build FFmpeg command
        # Using fast seeking (input seeking) for start time
        # ffmpeg -ss START -i INPUT -to END ...
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_time),
            "-i", input_path,
            "-to", str(end_time),
            "-c:v", video_codec,
            "-preset", video_preset,
            "-crf", str(video_crf),
            "-c:a", audio_codec,
            "-b:a", audio_bitrate,
            "-movflags", "+faststart",
            output_path
        ]
        
        logger.info(f"Running trim command: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            logger.error(f"FFmpeg trim error: {result.stderr}")
            raise Exception(f"FFmpeg failed: {result.stderr}")
            
        run_time = time.time() - start_ts
        
        return {
            "output_path": output_path,
            "run_time": run_time
        }
        
    finally:
        if os.path.exists(input_path):
            os.remove(input_path)
