"""
Video Source Overlay Module
Adds text overlay showing video source/channel info using FFmpeg drawtext filter.
"""

import subprocess
import os
import logging
import requests
import re

logger = logging.getLogger(__name__)


def download_video_from_url(video_url: str, output_path: str) -> str:
    """Download video from URL to local path"""
    internal_url = video_url
    
    # Handle hostname conflicts:
    # - minio:9000 is external MinIO (from NCAT toolkit), needs alias minio-nca
    # - localhost:9000 may also be used for external MinIO
    # - minio:9002 is internal MinIO (video-ai-pipeline)
    # - minio-video is n8n alias for internal MinIO
    
    # Convert external MinIO URL (port 9000) to use alias minio-nca
    internal_url = re.sub(r'http://minio:9000/', 'http://minio-nca:9000/', internal_url)
    internal_url = re.sub(r'http://localhost:9000/', 'http://minio-nca:9000/', internal_url)
    
    # Handle new minio-storage endpoint (port 9002)
    internal_url = re.sub(r'http://localhost:9002/', 'http://minio-storage:9002/', internal_url)
    internal_url = re.sub(r'http://127.0.0.1:9002/', 'http://minio-storage:9002/', internal_url)
    internal_url = internal_url.replace("minio_storage", "minio-storage")
    
    # Handle misconfigured n8n URL
    internal_url = re.sub(r'http://n8n-ncat:5678/', 'http://minio-storage:9002/', internal_url)
    
    # Convert n8n alias to internal hostname
    internal_url = internal_url.replace("minio-video", "minio")
    
    logger.info(f"Downloading video: {internal_url}")
    
    response = requests.get(internal_url, stream=True, timeout=120)
    response.raise_for_status()
    
    with open(output_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    
    logger.info(f"Video downloaded: {output_path}")
    return output_path


def parse_rgba_color(color_str: str) -> tuple:
    """
    Parse RGBA color string to FFmpeg format.
    Supports: rgba(r,g,b,a), #RRGGBB, #RGB
    Returns: (hex_color, alpha_float)
    """
    # Handle rgba format
    rgba_match = re.match(r'rgba?\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+))?\s*\)', color_str)
    if rgba_match:
        r, g, b = int(rgba_match.group(1)), int(rgba_match.group(2)), int(rgba_match.group(3))
        a = float(rgba_match.group(4)) if rgba_match.group(4) else 1.0
        hex_color = f"#{r:02x}{g:02x}{b:02x}"
        return hex_color, a
    
    # Handle hex format
    if color_str.startswith('#'):
        if len(color_str) == 4:  # #RGB
            r = int(color_str[1] * 2, 16)
            g = int(color_str[2] * 2, 16)
            b = int(color_str[3] * 2, 16)
            return f"#{r:02x}{g:02x}{b:02x}", 1.0
        return color_str, 1.0
    
    return color_str, 1.0


def get_position_coords(position: str, margin_x: int, margin_y: int) -> tuple:
    """
    Convert position name to FFmpeg x:y coordinates.
    Returns: (x_expr, y_expr) for FFmpeg drawtext filter
    """
    positions = {
        "top_left": (f"{margin_x}", f"{margin_y}"),
        "top_center": (f"(w-text_w)/2", f"{margin_y}"),
        "top_right": (f"w-text_w-{margin_x}", f"{margin_y}"),
        "center_left": (f"{margin_x}", f"(h-text_h)/2"),
        "center": (f"(w-text_w)/2", f"(h-text_h)/2"),
        "center_right": (f"w-text_w-{margin_x}", f"(h-text_h)/2"),
        "bottom_left": (f"{margin_x}", f"h-text_h-{margin_y}"),
        "bottom_center": (f"(w-text_w)/2", f"h-text_h-{margin_y}"),
        "bottom_right": (f"w-text_w-{margin_x}", f"h-text_h-{margin_y}"),
    }
    return positions.get(position, positions["bottom_right"])


def find_font_file(font_family: str) -> str:
    """Find font file path using fc-match"""
    try:
        result = subprocess.run(
            ["fc-match", "-f", "%{file}", font_family],
            capture_output=True,
            text=True
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception as e:
        logger.warning(f"fc-match failed: {e}")
    
    # Check local fonts directory
    fonts_dir = "/app/fonts"
    if os.path.exists(fonts_dir):
        for f in os.listdir(fonts_dir):
            if font_family.lower().replace(" ", "") in f.lower().replace(" ", ""):
                return os.path.join(fonts_dir, f)
    
    # Fallback to default
    return "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def add_video_source_to_video(
    video_url: str,
    job_id: str,
    channel_name: str,
    prefix: str = "FullVideo:",
    text_style: dict = None,
    background: dict = None,
    position: dict = None
) -> dict:
    """
    Add video source overlay to video using FFmpeg drawtext filter.
    
    Args:
        video_url: URL of the source video
        job_id: Unique job identifier
        channel_name: Channel name to display
        prefix: Text before channel name
        text_style: Font styling options
        background: Background box options
        position: Position on video
        
    Returns:
        dict with output_path
    """
    # Set defaults
    text_style = text_style or {}
    background = background or {}
    position = position or {}
    
    # Parse settings
    font_family = text_style.get("font_family", "Montserrat")
    font_size = text_style.get("font_size", 40)
    font_color = text_style.get("color", "#FFFFFF")
    bold = text_style.get("bold", True)
    italic = text_style.get("italic", False)
    
    bg_enabled = background.get("enabled", True)
    bg_color = background.get("color", "rgba(0, 0, 0, 0.5)")
    bg_padding = background.get("padding", 20)
    
    pos_name = position.get("position", "bottom_right")
    margin_x = position.get("margin_x", 30)
    margin_y = position.get("margin_y", 30)
    
    # Prepare paths
    input_path = f"/app/output/{job_id}_input.mp4"
    output_path = f"/app/output/{job_id}_output.mp4"
    
    # Download video
    download_video_from_url(video_url, input_path)
    
    # Build display text
    display_text = f"{prefix} {channel_name}".strip()
    # Escape special characters for FFmpeg
    display_text = display_text.replace(":", "\\:").replace("'", "\\'")
    
    # Find font file
    font_file = find_font_file(font_family)
    logger.info(f"Using font: {font_file}")
    
    # Get position coordinates
    x_expr, y_expr = get_position_coords(pos_name, margin_x, margin_y)
    
    # Parse colors
    font_hex, _ = parse_rgba_color(font_color)
    bg_hex, bg_alpha = parse_rgba_color(bg_color)
    
    # Build drawtext filter
    drawtext_parts = [
        f"text='{display_text}'",
        f"fontfile='{font_file}'",
        f"fontsize={font_size}",
        f"fontcolor={font_hex}",
        f"x={x_expr}",
        f"y={y_expr}",
    ]
    
    # Add background box if enabled
    if bg_enabled:
        # Convert alpha to FFmpeg format (0-1 to hex 00-FF)
        alpha_hex = format(int(bg_alpha * 255), '02x')
        box_color = f"{bg_hex}@{bg_alpha}"
        drawtext_parts.extend([
            "box=1",
            f"boxcolor={box_color}",
            f"boxborderw={bg_padding}",
        ])
    
    drawtext_filter = ":".join(drawtext_parts)
    
    # Build FFmpeg command
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf", f"drawtext={drawtext_filter}",
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
    
    # Cleanup input file
    if os.path.exists(input_path):
        os.remove(input_path)
        logger.info(f"Cleaned up: {input_path}")
    
    logger.info(f"Video source overlay added: {output_path}")
    
    return {
        "output_path": output_path,
        "display_text": display_text.replace("\\:", ":").replace("\\'", "'")
    }
