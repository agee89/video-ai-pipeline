"""
Image to Video Module
Creates video from images using FFmpeg.
Supports multiple images with transitions.
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


def get_motion_filter(motion: str, width: int, height: int, duration: float, fps: int, intensity: float = 0.3) -> str:
    """
    Generate FFmpeg filter for Ken Burns motion effects.
    
    Args:
        motion: Effect type (zoom_in, zoom_out, pan_left, pan_right, pan_up, pan_down)
        width: Output width
        height: Output height
        duration: Duration in seconds
        fps: Frames per second
        intensity: Zoom/pan intensity 0.1-1.0 (default 0.3 = 30% zoom)
    
    Returns:
        FFmpeg filter string
    """
    total_frames = int(duration * fps)
    
    # Clamp intensity between 0.1 and 1.0
    intensity = max(0.1, min(1.0, intensity))
    
    # Zoom factor based on intensity (1.0 to 1.0+intensity)
    zoom_start = 1.0
    zoom_end = 1.0 + intensity
    zoom_step = (zoom_end - zoom_start) / total_frames
    
    if motion == "zoom_in":
        # Zoom in from center
        return f"zoompan=z='min(zoom+{zoom_step:.6f},{zoom_end})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={total_frames}:s={width}x{height}:fps={fps}"
    
    elif motion == "zoom_out":
        # Zoom out from center
        return f"zoompan=z='if(lte(zoom,1.0),{zoom_end},max(1.0,zoom-{zoom_step:.6f}))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={total_frames}:s={width}x{height}:fps={fps}"
    
    elif motion == "pan_left":
        # Pan from right to left
        return f"zoompan=z='{zoom_end}':x='iw-iw/zoom-(iw-iw/zoom)*on/{total_frames}':y='ih/2-(ih/zoom/2)':d={total_frames}:s={width}x{height}:fps={fps}"
    
    elif motion == "pan_right":
        # Pan from left to right
        return f"zoompan=z='{zoom_end}':x='(iw-iw/zoom)*on/{total_frames}':y='ih/2-(ih/zoom/2)':d={total_frames}:s={width}x{height}:fps={fps}"
    
    elif motion == "pan_up":
        # Pan from bottom to top
        return f"zoompan=z='{zoom_end}':x='iw/2-(iw/zoom/2)':y='ih-ih/zoom-(ih-ih/zoom)*on/{total_frames}':d={total_frames}:s={width}x{height}:fps={fps}"
    
    elif motion == "pan_down":
        # Pan from top to bottom
        return f"zoompan=z='{zoom_end}':x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*on/{total_frames}':d={total_frames}:s={width}x{height}:fps={fps}"
    
    elif motion == "zoom_in_pan_right":
        # Zoom in while panning right
        return f"zoompan=z='min(zoom+{zoom_step:.6f},{zoom_end})':x='(iw-iw/zoom)*on/{total_frames}':y='ih/2-(ih/zoom/2)':d={total_frames}:s={width}x{height}:fps={fps}"
    
    elif motion == "zoom_in_pan_left":
        # Zoom in while panning left
        return f"zoompan=z='min(zoom+{zoom_step:.6f},{zoom_end})':x='iw-iw/zoom-(iw-iw/zoom)*on/{total_frames}':y='ih/2-(ih/zoom/2)':d={total_frames}:s={width}x{height}:fps={fps}"
    
    else:
        return None


def create_video_from_images(
    images: list,
    job_id: str,
    fps: int = 30,
    transition: str = None,
    motion: str = None,
    motion_intensity: float = 0.3
) -> dict:
    """
    Create video from images using FFmpeg.
    
    Args:
        images: List of dicts with image_url and duration
        job_id: Unique job identifier
        fps: Frames per second
        transition: Transition effect (fade, wipeleft, etc)
        motion: Motion effect (zoom_in, zoom_out, pan_left, etc)
        motion_intensity: Zoom/pan intensity 0.1-1.0 (default 0.3)
        
    Returns:
        dict with output_path
    """
    if len(images) < 1:
        raise ValueError("At least 1 image is required")
    
    # Prepare paths
    output_dir = "/app/output"
    image_paths = []
    output_path = f"{output_dir}/{job_id}_video.mp4"
    
    # Target resolution (portrait)
    width = 1080
    height = 1920
    
    try:
        # Download all images
        for i, img in enumerate(images):
            ext = img["image_url"].split(".")[-1].split("?")[0] or "jpg"
            image_path = f"{output_dir}/{job_id}_img_{i}.{ext}"
            download_file(img["image_url"], image_path)
            image_paths.append({
                "path": image_path,
                "duration": img.get("duration", 3.0)
            })
        
        if len(image_paths) == 1:
            # Single image - with optional motion effect
            img = image_paths[0]
            duration = img["duration"]
            
            if motion:
                # Apply Ken Burns motion effect
                motion_filter = get_motion_filter(motion, width, height, duration, fps, motion_intensity)
                if motion_filter:
                    cmd = [
                        "ffmpeg", "-y",
                        "-loop", "1",
                        "-i", img["path"],
                        "-vf", motion_filter,
                        "-c:v", "libx264",
                        "-t", str(duration),
                        "-pix_fmt", "yuv420p",
                        output_path
                    ]
                    logger.info(f"Creating video with motion '{motion}': {img['path']}")
                else:
                    # Invalid motion, fall back to static
                    cmd = [
                        "ffmpeg", "-y",
                        "-loop", "1",
                        "-i", img["path"],
                        "-c:v", "libx264",
                        "-t", str(duration),
                        "-pix_fmt", "yuv420p",
                        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1",
                        "-r", str(fps),
                        output_path
                    ]
                    logger.info(f"Creating static video: {img['path']}")
            else:
                # Static image
                cmd = [
                    "ffmpeg", "-y",
                    "-loop", "1",
                    "-i", img["path"],
                    "-c:v", "libx264",
                    "-t", str(duration),
                    "-pix_fmt", "yuv420p",
                    "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1",
                    "-r", str(fps),
                    output_path
                ]
                logger.info(f"Creating video from single image: {img['path']}")
            
        else:
            # Multiple images - create slideshow with optional transitions
            
            # Supported xfade transitions for woosh sounds
            TRANSITION_MAP = {
                "fade": "fade",
                "wipeleft": "wipeleft",
                "wiperight": "wiperight",
                "wipeup": "wipeup",
                "wipedown": "wipedown",
                "slideleft": "slideleft",
                "slideright": "slideright",
                "slideup": "slideup",
                "slidedown": "slidedown",
                "circlecrop": "circlecrop",
                "circleopen": "circleopen",
                "circleclose": "circleclose",
                "dissolve": "dissolve",
                "pixelize": "pixelize",
                "radial": "radial",
                "horzopen": "horzopen",
                "horzclose": "horzclose",
                "vertopen": "vertopen",
                "vertclose": "vertclose",
            }
            
            if transition and transition in TRANSITION_MAP:
                # Use xfade for transitions
                xfade_type = TRANSITION_MAP[transition]
                trans_duration = 0.5
                
                # Build filter complex for transitions
                input_args = []
                filter_parts = []
                
                for i, img in enumerate(image_paths):
                    input_args.extend(["-loop", "1", "-t", str(img["duration"]), "-i", img["path"]])
                
                # Scale all inputs
                for i in range(len(image_paths)):
                    filter_parts.append(f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}[v{i}]")
                
                # Chain xfade transitions
                if len(image_paths) == 2:
                    offset = image_paths[0]["duration"] - trans_duration
                    filter_parts.append(f"[v0][v1]xfade=transition={xfade_type}:duration={trans_duration}:offset={offset}[outv]")
                else:
                    # For 3+ images, chain transitions
                    offset = image_paths[0]["duration"] - trans_duration
                    filter_parts.append(f"[v0][v1]xfade=transition={xfade_type}:duration={trans_duration}:offset={offset}[tmp0]")
                    
                    for i in range(2, len(image_paths)):
                        prev_label = f"tmp{i-2}" if i > 2 else "tmp0"
                        offset += image_paths[i-1]["duration"] - trans_duration
                        if i == len(image_paths) - 1:
                            filter_parts.append(f"[{prev_label}][v{i}]xfade=transition={xfade_type}:duration={trans_duration}:offset={offset}[outv]")
                        else:
                            filter_parts.append(f"[{prev_label}][v{i}]xfade=transition={xfade_type}:duration={trans_duration}:offset={offset}[tmp{i-1}]")
                
                filter_complex = ";".join(filter_parts)
                
                cmd = [
                    "ffmpeg", "-y",
                    *input_args,
                    "-filter_complex", filter_complex,
                    "-map", "[outv]",
                    "-c:v", "libx264",
                    "-preset", "fast",
                    "-crf", "23",
                    "-pix_fmt", "yuv420p",
                    output_path
                ]
            else:
                # No transition - simple concat
                input_args = []
                filter_parts = []
                
                for i, img in enumerate(image_paths):
                    input_args.extend(["-loop", "1", "-t", str(img["duration"]), "-i", img["path"]])
                    filter_parts.append(f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}[v{i}]")
                
                concat_inputs = "".join([f"[v{i}]" for i in range(len(image_paths))])
                filter_parts.append(f"{concat_inputs}concat=n={len(image_paths)}:v=1[outv]")
                
                filter_complex = ";".join(filter_parts)
                
                cmd = [
                    "ffmpeg", "-y",
                    *input_args,
                    "-filter_complex", filter_complex,
                    "-map", "[outv]",
                    "-c:v", "libx264",
                    "-preset", "fast",
                    "-crf", "23",
                    "-pix_fmt", "yuv420p",
                    output_path
                ]
            
            logger.info(f"Creating slideshow from {len(image_paths)} images")
        
        logger.info(f"Running FFmpeg: {' '.join(cmd[:10])}...")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr}")
            raise Exception(f"FFmpeg failed: {result.stderr}")
        
        logger.info(f"Video created: {output_path}")
        
        return {
            "output_path": output_path,
            "image_count": len(images),
            "transition": transition
        }
        
    finally:
        # Cleanup input files
        for img in image_paths:
            if os.path.exists(img["path"]):
                os.remove(img["path"])
                logger.info(f"Cleaned up: {img['path']}")
