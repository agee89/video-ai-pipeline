"""
Image Watermark Module
Adds image overlay (logo, watermark) to videos using FFmpeg overlay filter.
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
    internal_url = internal_url.replace("minio-video", "minio")
    
    logger.info(f"Downloading: {internal_url}")
    
    response = requests.get(internal_url, stream=True, timeout=120)
    response.raise_for_status()
    
    with open(output_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    
    logger.info(f"Downloaded: {output_path}")
    return output_path


def get_overlay_position(position: str, margin_x: int, margin_y: int) -> str:
    """
    Convert position name to FFmpeg overlay filter coordinates.
    Uses overlay_w and overlay_h for watermark dimensions.
    """
    positions = {
        "top_left": f"{margin_x}:{margin_y}",
        "top_center": f"(main_w-overlay_w)/2:{margin_y}",
        "top_right": f"main_w-overlay_w-{margin_x}:{margin_y}",
        "center": f"(main_w-overlay_w)/2:(main_h-overlay_h)/2",
        "bottom_left": f"{margin_x}:main_h-overlay_h-{margin_y}",
        "bottom_center": f"(main_w-overlay_w)/2:main_h-overlay_h-{margin_y}",
        "bottom_right": f"main_w-overlay_w-{margin_x}:main_h-overlay_h-{margin_y}",
    }
    return positions.get(position, positions["bottom_right"])


def add_image_watermark_to_video(
    video_url: str,
    image_url: str,
    job_id: str,
    size: dict = None,
    position: dict = None,
    opacity: float = 1.0
) -> dict:
    """
    Add image watermark to video using FFmpeg overlay filter.
    
    Args:
        video_url: URL of the source video
        image_url: URL of watermark image
        job_id: Unique job identifier
        size: Resize options (width, height, scale)
        position: Position options (position, margin_x, margin_y)
        opacity: Transparency 0.0-1.0
        
    Returns:
        dict with output_path
    """
    size = size or {}
    position = position or {}
    
    # Parse options
    width = size.get("width")
    height = size.get("height")
    scale = size.get("scale")
    
    pos_name = position.get("position", "bottom_right")
    margin_x = position.get("margin_x", 30)
    margin_y = position.get("margin_y", 30)
    
    # Clamp opacity
    opacity = max(0.0, min(1.0, opacity))
    
    # Prepare paths
    video_path = f"/app/output/{job_id}_input.mp4"
    image_path = f"/app/output/{job_id}_watermark.png"
    output_path = f"/app/output/{job_id}_output.mp4"
    
    # Download files
    download_file(video_url, video_path)
    download_file(image_url, image_path)
    
    # Build filter complex
    filter_parts = []
    
    # Resize watermark if needed
    if scale:
        filter_parts.append(f"[1:v]scale=iw*{scale}:ih*{scale}[wm]")
    elif width and height:
        filter_parts.append(f"[1:v]scale={width}:{height}[wm]")
    elif width:
        filter_parts.append(f"[1:v]scale={width}:-1[wm]")
    elif height:
        filter_parts.append(f"[1:v]scale=-1:{height}[wm]")
    else:
        # No resize
        filter_parts.append("[1:v]null[wm]")
    
    # Apply opacity if not fully opaque
    if opacity < 1.0:
        filter_parts.append(f"[wm]format=rgba,colorchannelmixer=aa={opacity}[wm_alpha]")
        watermark_label = "wm_alpha"
    else:
        watermark_label = "wm"
    
    # Get overlay position
    overlay_coords = get_overlay_position(pos_name, margin_x, margin_y)
    
    # Add overlay filter
    filter_parts.append(f"[0:v][{watermark_label}]overlay={overlay_coords}")
    
    filter_complex = ";".join(filter_parts)
    
    # Build FFmpeg command
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", image_path,
        "-filter_complex", filter_complex,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "copy",
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
    
    # Cleanup input files
    for f in [video_path, image_path]:
        if os.path.exists(f):
            os.remove(f)
            logger.info(f"Cleaned up: {f}")
    
    logger.info(f"Image watermark added: {output_path}")
    
    return {
        "output_path": output_path,
        "position": pos_name,
        "opacity": opacity
    }
