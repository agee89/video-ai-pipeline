"""
Video Merge Module
Concatenates multiple videos into one using FFmpeg concat demuxer.
"""

import subprocess
import os
import logging
import requests
import re

logger = logging.getLogger(__name__)


def download_file(url: str, output_path: str) -> str:
    """Download file from URL to local path"""
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
    
    internal_url = internal_url.replace("minio-video", "minio")
    
    logger.info(f"Downloading: {internal_url}")
    
    response = requests.get(internal_url, stream=True, timeout=300)
    response.raise_for_status()
    
    with open(output_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    
    logger.info(f"Downloaded: {output_path}")
    return output_path


def merge_videos(
    video_urls: list,
    job_id: str
) -> dict:
    """
    Merge multiple videos into one using FFmpeg concat demuxer.
    
    Args:
        video_urls: List of video URLs to merge (in order)
        job_id: Unique job identifier
        
    Returns:
        dict with output_path
    """
    if len(video_urls) < 2:
        raise ValueError("At least 2 videos are required to merge")
    
    # Prepare paths
    output_dir = "/app/output"
    video_paths = []
    concat_list_path = f"{output_dir}/{job_id}_concat.txt"
    output_path = f"{output_dir}/{job_id}_merged.mp4"
    
    try:
        # Download all videos
        for i, url in enumerate(video_urls):
            video_path = f"{output_dir}/{job_id}_input_{i}.mp4"
            download_file(url, video_path)
            video_paths.append(video_path)
        
        # Build FFmpeg command using filter_complex for better compatibility
        # This re-encodes all videos to ensure consistent format
        input_args = []
        for path in video_paths:
            input_args.extend(["-i", path])
        
        # Build filter_complex string with scale to normalize dimensions
        # Scale all videos to 1080x1920 (portrait) and resample audio to 44100Hz
        filter_parts = []
        for i in range(len(video_paths)):
            # Scale video to 1080x1920, pad if needed to maintain aspect ratio
            filter_parts.append(f"[{i}:v]scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1[v{i}]")
            # Normalize audio to stereo 44100Hz
            filter_parts.append(f"[{i}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}]")
        
        # Build concat input labels
        concat_inputs = ""
        for i in range(len(video_paths)):
            concat_inputs += f"[v{i}][a{i}]"
        
        filter_parts.append(f"{concat_inputs}concat=n={len(video_paths)}:v=1:a=1[outv][outa]")
        
        filter_complex = ";".join(filter_parts)
        
        cmd = [
            "ffmpeg", "-y",
            *input_args,
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-map", "[outa]",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            output_path
        ]
        
        logger.info(f"Running FFmpeg: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr}")
            raise Exception(f"FFmpeg failed: {result.stderr}")
        
        logger.info(f"Videos merged: {output_path}")
        
        return {
            "output_path": output_path,
            "video_count": len(video_urls)
        }
        
    finally:
        # Cleanup input files
        for path in video_paths:
            if os.path.exists(path):
                os.remove(path)
                logger.info(f"Cleaned up: {path}")
