"""
Overlay Notification Module
Adds a video overlay (e.g. subscribe animation) to a source video with chroma key support.
"""

import os
import subprocess
import logging
import json
import re
from PIL import Image
import numpy as np
from .fetcher import download_video
from .exporter import upload_to_storage

logger = logging.getLogger(__name__)

def get_dominant_color_from_corners(image_path: str) -> str:
    """
    Analyze the corners of the first frame to find the dominant background color.
    Returns hex color string (e.g. 0x00FF00)
    """
    try:
        img = Image.open(image_path)
        img = img.convert("RGB")
        w, h = img.size
        
        # Sample corners (10x10 pixels)
        corners = []
        sample_size = 10
        
        # Define regions: top-left, top-right, bottom-left, bottom-right
        regions = [
            (0, 0, sample_size, sample_size),
            (w-sample_size, 0, w, sample_size),
            (0, h-sample_size, sample_size, h),
            (w-sample_size, h-sample_size, w, h)
        ]
        
        for region in regions:
            crop = img.crop(region)
            corners.append(np.array(crop))
            
        # Concatenate all samples
        all_pixels = np.concatenate([c.reshape(-1, 3) for c in corners])
        
        # Find most common color
        # Quantize to reduce noise? For now, just mean or median might be safer, 
        # but exact mode is good for digital green screens.
        # Let's use binning to find the peak color.
        
        colors, counts = np.unique(all_pixels, axis=0, return_counts=True)
        dominant_idx = np.argmax(counts)
        dominant_color = colors[dominant_idx]
        
        # Convert to hex 0xRRGGBB
        hex_color = "0x{:02X}{:02X}{:02X}".format(dominant_color[0], dominant_color[1], dominant_color[2])
        logger.info(f"Auto-detected background color: {hex_color} (RGB: {dominant_color})")
        return hex_color
        
    except Exception as e:
        logger.error(f"Failed to auto-detect color: {e}")
        return "0x00FF00" # Fallback to Green

def get_content_bbox(image_path: str, hex_color: str, tolerance: int = 40) -> dict:
    """
    Find bounding box of content that is NOT the background color.
    hex_color: 0xRRGGBB
    """
    try:
        img = Image.open(image_path).convert("RGB")
        data = np.array(img)
        
        # Parse hex color
        hex_color = hex_color.replace("0x", "").replace("#", "")
        r_target = int(hex_color[0:2], 16)
        g_target = int(hex_color[2:4], 16)
        b_target = int(hex_color[4:6], 16)
        
        # Calculate distance (simple euclidean in RGB)
        # We can also key mask exactly like ffmpeg but simple diff is usually enough for crop
        diff = np.sqrt(np.sum((data - np.array([r_target, g_target, b_target])) ** 2, axis=2))
        
        # Mask: True where pixel is NOT background (distance > tolerance)
        mask = diff > tolerance
        
        coords = np.argwhere(mask)
        if coords.size == 0:
            return None # Empty or full background
            
        y_min, x_min = coords.min(axis=0)
        y_max, x_max = coords.max(axis=0)
        
        # Add a safer padding to accommodate animation movement/scaling
        # Since chroma key runs after crop, extra background is fine (it becomes transparent).
        # Too tight crop is bad (cuts off animation).
        padding = 50 
        h, w, _ = data.shape
        
        x_min = max(0, x_min - padding)
        y_min = max(0, y_min - padding)
        x_max = min(w, x_max + padding)
        y_max = min(h, y_max + padding)
        
        # Logging to help debug bounds
        # logger.info(f"Crop bbox calculated: x={x_min}, y={y_min}, w={x_max-x_min}, h={y_max-y_min} (Padding: {padding})")
        
        return {
            "x": int(x_min),
            "y": int(y_min),
            "w": int(x_max - x_min),
            "h": int(y_max - y_min)
        }
    except Exception as e:
        logger.error(f"Error in auto-crop: {e}")
        return None

def get_video_duration(video_path: str) -> float:
    """Get video duration using ffprobe"""
    try:
        cmd = [
            "ffprobe", 
            "-v", "error", 
            "-show_entries", "format=duration", 
            "-of", "default=noprint_wrappers=1:nokey=1", 
            video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return float(result.stdout.strip())
    except Exception:
        return 0.0

def process_overlay_notification(
    video_url: str,
    overlay_url: str,
    job_id: str,
    start_time: str = None, # "MM:SS"
    position: dict = None,
    resize: dict = None,
    chroma_key: dict = None
) -> dict:
    
    # Defaults
    position = position or {}
    resize = resize or {}
    chroma_key = chroma_key or {}
    
    output_dir = "/app/output"
    os.makedirs(output_dir, exist_ok=True)
    
    input_video_path = f"{output_dir}/{job_id}_main.mp4"
    overlay_video_path = f"{output_dir}/{job_id}_overlay.mp4" # Or whatever ext
    output_path = f"{output_dir}/{job_id}_out.mp4"
    
    try:
        # 1. Download Videos
        logger.info("Downloading main video...")
        download_video(video_url, job_id + "_main", output_path=input_video_path)
        
        logger.info("Downloading overlay video...")
        download_video(overlay_url, job_id + "_overlay", output_path=overlay_video_path)
        
        # 2. Determine Chroma Key Color
        key_color = chroma_key.get("color")
        similarity = chroma_key.get("similarity", 0.3)
        blend = chroma_key.get("blend", 0.1)
        auto_detect = chroma_key.get("auto", True)
        auto_detect = chroma_key.get("auto", True)
        auto_crop = chroma_key.get("crop", True) # Default True for smart positioning
        
        # Extract frame to analyze (color and crop)
        # BUG FIX: Use middle frame instead of first frame, in case start is blank/fade-in
        ov_duration = get_video_duration(overlay_video_path)
        midpoint = max(0, ov_duration / 2)
        
        frame_path = f"{output_dir}/{job_id}_frame.png"
        subprocess.run([
            "ffmpeg", "-y", 
            "-ss", str(midpoint),
            "-i", overlay_video_path, 
            "-vframes", "1", frame_path
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        if not key_color and auto_detect:
            key_color = get_dominant_color_from_corners(frame_path)
        
        if not key_color:
            key_color = "0x00FF00" # Default Green
            
        # Ensure 0x prefix
        if key_color.startswith("#"):
            key_color = "0x" + key_color[1:]

        # Auto Crop Logic
        crop_filter = ""
        if auto_crop:
            bbox = get_content_bbox(frame_path, key_color)
            if bbox:
                logger.info(f"Auto-crop determined: {bbox}")
                # crop=w:h:x:y
                crop_filter = f"crop={bbox['w']}:{bbox['h']}:{bbox['x']}:{bbox['y']}"
            else:
                logger.warning("Auto-crop failed to find content (mask empty), using full frame.")

        if os.path.exists(frame_path):
            os.remove(frame_path)
            
        # 3. resizing Logic
            
        # 3. resizing Logic
        # scale=w:h
        # If user provides percentage (scale=0.5), we need to know dimension or use relative
        # Simple approach: if width/height provided use them, else if scale provided use iw*scale:ih*scale
        scale_filter = ""
        target_w = resize.get("width")
        target_h = resize.get("height")
        scale_factor = resize.get("scale")
        
        if target_w or target_h:
            w = target_w if target_w else "-1"
            h = target_h if target_h else "-1"
            scale_filter = f"scale={w}:{h}"
        elif scale_factor:
            scale_filter = f"scale=iw*{scale_factor}:ih*{scale_factor}"
        
        # 4. Position and Timing Logic
        # Position
        pos_x = position.get("x", "W-w-30") # Default bottom right with margin
        pos_y = position.get("y", "H-h-30")
        
        # Handle presets if needed, but the API might pass raw strings like "10" or "(W-w)/2"
        # Let's assume the API or consumer handles mapping simplified "top_right" to ffmpeg expressions, 
        # or we do it here.
        # Let's support basic keywords mapping here for robustness
        margin_x = position.get("margin_x", 30)
        margin_y = position.get("margin_y", 30)
        preset = position.get("preset") # top_left, top_right, bottom_left, bottom_right, center
        
        if preset == "top_left":
            pos_x, pos_y = f"{margin_x}", f"{margin_y}"
        elif preset == "top_right":
            pos_x, pos_y = f"W-w-{margin_x}", f"{margin_y}"
        elif preset == "bottom_left":
            pos_x, pos_y = f"{margin_x}", f"H-h-{margin_y}"
        elif preset == "bottom_center":
            pos_x, pos_y = f"(W-w)/2", f"H-h-{margin_y}"
        elif preset == "top_center":
            pos_x, pos_y = f"(W-w)/2", f"{margin_y}"
        elif preset == "center":
            pos_x, pos_y = f"(W-w)/2", f"(H-h)/2"
        elif preset == "bottom_right":
            pos_x, pos_y = f"W-w-{margin_x}", f"H-h-{margin_y}"
            
        logger.info(f"Positioning: Preset={preset}, X={pos_x}, Y={pos_y} (Margins: {margin_x}, {margin_y})")
            
        # Timing
        # enable='between(t,START,END)' or itsoffset
        # We need start seconds.
        
        main_duration = get_video_duration(input_video_path)
        overlay_duration = ov_duration # Optimized, already calculated
        
        start_seconds = 0
        if start_time:
            if str(start_time).startswith("end"):
                # Auto-calculate start time so overlay ends when main video ends
                # Support offsets: "end", "end-2", "end+1.5"
                offset = 0.0
                if len(str(start_time)) > 3:
                     try:
                         offset_str = str(start_time)[3:]
                         offset = float(offset_str)
                     except ValueError:
                         logger.warning(f"Invalid end offset format: {start_time}, ignoring offset")

                start_seconds = max(0, main_duration - overlay_duration + offset)
                logger.info(f"Auto 'end' timing: start_seconds={start_seconds} (Main: {main_duration}s, Overlay: {overlay_duration}s, Offset: {offset}s)")
            else:
                parts = start_time.split(":")
                if len(parts) == 2:
                    start_seconds = int(parts[0]) * 60 + float(parts[1])
                elif len(parts) == 3:
                    start_seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        
        # We ideally want the overlay to just play once at that time.
        # overlay filter option: enable='between(t,start,start+duration)'
        
        end_seconds = start_seconds + overlay_duration
        
        enable_expr = f"between(t,{start_seconds},{end_seconds})"
        
        # 5. Build Filter Complex
        # [1:v] -> [scaled] (optional) -> [keyed] -> [overlay]
        
        filters = []
        current_stream = "1:v"
        
        # Auto Crop
        if crop_filter:
            filters.append(f"[{current_stream}]{crop_filter}[cropped]")
            current_stream = "cropped"
        
        # Resize
        if scale_filter:
            filters.append(f"[{current_stream}]{scale_filter}[scaled]")
            current_stream = "scaled"
            
        # Chroma Key
        # colorkey=color:similarity:blend
        filters.append(f"[{current_stream}]colorkey={key_color}:{similarity}:{blend}[keyed]")
        current_stream = "keyed"
        
        # Overlay
        # We need to offset the timestamp of the overlay video so it starts playing at start_time?
        # Actually `overlay` filter with `enable` just shows/hides it. 
        # If the overlay video is short and loops, valid. But usually it plays from 0.
        # If we want it to start playing from 0 AT start_time, we might need `itsoffset` on input
        # or `setpts=PTS+START_TB`.
        # FFmpeg overlay documentation: "If the enable expression evaluates to 0, the overlay is not shown."
        # However, the overlay video stream continues to advance in time even when not shown.
        # So if we want it to START at T=10, we need to delay the overlay stream.
        
        # Delay overlay stream
        filters.append(f"[{current_stream}]setpts=PTS+{start_seconds}/TB[delayed]")
        current_stream = "delayed"
        
        # Final Overlay
        # eof_action=pass passes the main video through when overlay ends
        overlay_filter = f"[0:v][{current_stream}]overlay=x={pos_x}:y={pos_y}:eof_action=pass[outv]"

        # Audio mixing logic
        # We need to mix 0:a and 1:a (delayed) using amix.
        # Delaying audio in ffmpeg can be done with adelay filter.
        # adelay=delays, delays is in milliseconds.
        
        delay_ms = int(start_seconds * 1000)
        audio_filters = []
        mixed_audio = False
        
        # Check if overlay has audio (simple check, or just try to map it)
        # Better: use [0:a] and [1:a], delay [1:a], then amix.
        # If one input lacks audio, amix might fail or we need to be careful.
        # Let's assume for now both have audio or we try to handle it.
        # Safest is to use -map 0:a? and -map 1:a? but proper mixing needs filter graph.
        
        # Construct audio filter graph
        # [1:a]adelay=1000|1000[delayed_a];[0:a][delayed_a]amix=inputs=2:duration=first:dropout_transition=2[outa]
        # We need to detect if inputs have audio streams to avoid errors.
        
        # Probing for audio streams
        has_audio_main = False
        has_audio_overlay = False
        
        try:
            probe_cmd = ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", input_video_path]
            if subprocess.run(probe_cmd, capture_output=True, text=True).stdout.strip():
                has_audio_main = True
                
            probe_cmd = ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", overlay_video_path]
            if subprocess.run(probe_cmd, capture_output=True, text=True).stdout.strip():
                has_audio_overlay = True
        except:
            pass
            
        filters.append(overlay_filter) # Add video overlay filter first
        
        audio_map = []
        if has_audio_main and has_audio_overlay:
            # Mix both
            # Note: adelay takes delays for each channel. For stereo: delay|delay
            filters.append(f"[1:a]adelay={delay_ms}|{delay_ms}[delayed_a]")
            filters.append(f"[0:a][delayed_a]amix=inputs=2:duration=first:dropout_transition=2[outa]")
            audio_map = ["-map", "[outa]"]
            mixed_audio = True
        elif has_audio_main:
            audio_map = ["-map", "0:a"]
        elif has_audio_overlay:
            filters.append(f"[1:a]adelay={delay_ms}|{delay_ms}[outa]")
            audio_map = ["-map", "[outa]"]
            mixed_audio = True # Encoded
        
        filter_complex = ";".join(filters)
        
        cmd = [
            "ffmpeg", "-y",
            "-i", input_video_path,
            "-i", overlay_video_path,
            "-filter_complex", filter_complex,
            "-map", "[outv]"
        ]
        
        cmd.extend(audio_map)
        
        cmd.extend([
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        ])
        
        if mixed_audio:
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])
        else:
             cmd.extend(["-c:a", "copy"]) # If only main audio and no mixing
             
        cmd.append(output_path)
        
        logger.info(f"Running FFmpeg: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)
        
        return {
            "output_path": output_path,
            "details": {
                "key_color": key_color,
                "start_time": start_seconds,
                "position": preset or "custom"
            }
        }
        
    finally:
        # Cleanup inputs
        if os.path.exists(input_video_path):
            os.remove(input_video_path)
        if os.path.exists(overlay_video_path):
            os.remove(overlay_video_path)
