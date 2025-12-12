"""
Video Source Overlay Module
Adds text overlay showing video source/channel info using Pillow for image generation
and FFmpeg for overlaying the generated image.
"""

import subprocess
import os
import logging
import requests
import re
from PIL import Image, ImageDraw, ImageFont

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
    internal_url = internal_url.replace("minio-video", "minio-storage")
    
    logger.info(f"Downloading video: {internal_url}")
    
    try:
        # Use session with retries and User-Agent
        session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(max_retries=3)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = session.get(internal_url, stream=True, timeout=120, headers=headers)
        response.raise_for_status()
        
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                
        logger.info(f"Video downloaded: {output_path}")
        return output_path
    
    except Exception as e:
        logger.error(f"Failed to download video: {e}")
        # Try original URL as fallback if replacement failed logic
        if internal_url != video_url:
            logger.info(f"Retrying with original URL: {video_url}")
            try:
                urllib.request.urlretrieve(video_url, output_path)
                return output_path
            except Exception as e2:
                pass
        raise e


def parse_rgba_color(color_str: str) -> tuple:
    """
    Parse RGBA/Hex color string to (R, G, B, A) tuple for Pillow
    Returns: (r, g, b, a) where values are 0-255
    """
    # Defaults
    r, g, b, a = 255, 255, 255, 255
    
    color_str = color_str.strip().lower()
    
    # Handle rgba(r, g, b, a)
    rgba_match = re.match(r'rgba?\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+))?\s*\)', color_str)
    if rgba_match:
        r, g, b = int(rgba_match.group(1)), int(rgba_match.group(2)), int(rgba_match.group(3))
        alpha_float = float(rgba_match.group(4)) if rgba_match.group(4) else 1.0
        a = int(alpha_float * 255)
        return (r, g, b, a)
    
    # Handle hex format #RRGGBB or #RGB
    if color_str.startswith('#'):
        hex_str = color_str.lstrip('#')
        if len(hex_str) == 3:
            hex_str = ''.join([c*2 for c in hex_str])
        if len(hex_str) == 6:
            r = int(hex_str[0:2], 16)
            g = int(hex_str[2:4], 16)
            b = int(hex_str[4:6], 16)
            return (r, g, b, 255)
    
    return (r, g, b, a)


def find_font_file(font_family: str, bold: bool = False, italic: bool = False) -> str:
    """
    Find font file path.
    Priority 1: Check /app/fonts for exact Family Name match (using fontTools).
    Priority 2: System fc-match.
    """
    try:
        from fontTools.ttLib import TTFont
        font_dir = "/app/fonts"
        
        # 1. Scan /app/fonts if exists
        if os.path.exists(font_dir):
            # We could cache this, but for now scan on demand (or rely on OS cache if we registered)
            # To avoid slow scan every time, ideally this is cached. 
            # But let's just do a quick scan of TTF/OTF files.
            for f in os.listdir(font_dir):
                if not f.lower().endswith(('.ttf', '.otf')):
                    continue
                
                full_path = os.path.join(font_dir, f)
                try:
                    font = TTFont(full_path)
                    family_name = ""
                    for record in font['name'].names:
                        if record.nameID == 1: 
                            family_name = record.string.decode(record.getEncoding())
                            break
                    if not family_name:
                         for record in font['name'].names:
                            if record.nameID == 4:
                                family_name = record.string.decode(record.getEncoding())
                                break
                    
                    if family_name:
                        # Clean nulls
                        family_name = family_name.replace('\x00', '')
                        
                        # Compare case-insensitive
                        if family_name.strip().lower() == font_family.strip().lower():
                            logger.info(f"Found local font match: {font_family} -> {full_path}")
                            return full_path
                except:
                    continue
    except Exception as e:
        logger.warning(f"Error scanning local fonts: {e}")

    # 2. Fallback to fc-match
    style_query = ""
    if bold and italic:
        style_query = ":bold:italic"
    elif bold:
        style_query = ":bold"
    elif italic:
        style_query = ":italic"
        
    query = f"{font_family}{style_query}"
    
    try:
        result = subprocess.run(
            ["fc-match", "-f", "%{file}", query],
            capture_output=True,
            text=True
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception as e:
        logger.warning(f"fc-match failed: {e}")
    
    # Fallback to default
    return "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def create_overlay_image(
    prefix: str,
    channel_name: str,
    prefix_style: dict,
    channel_style: dict,
    background: dict,
    output_path: str
):
    """Generates the overlay image using Pillow"""
    
    # 1. Parse Styles
    # Prefix Params
    p_font_family = prefix_style.get("font_family", "Montserrat")
    p_font_size = prefix_style.get("font_size", 40)
    p_color = parse_rgba_color(prefix_style.get("color", "#FFFFFF"))
    p_bold = prefix_style.get("bold", True)
    p_italic = prefix_style.get("italic", False)
    p_stroke_color = parse_rgba_color(prefix_style.get("stroke_color") or "#000000")
    p_stroke_width = prefix_style.get("stroke_width", 0)
    
    # Channel Params
    c_font_family = channel_style.get("font_family", "Montserrat")
    c_font_size = channel_style.get("font_size", 40)
    c_color = parse_rgba_color(channel_style.get("color", "#FFFFFF"))
    c_bold = channel_style.get("bold", True)
    c_italic = channel_style.get("italic", False)
    c_stroke_color = parse_rgba_color(channel_style.get("stroke_color") or "#000000")
    c_stroke_width = channel_style.get("stroke_width", 0)
    
    # Background Params
    bg_enabled = background.get("enabled", True)
    bg_color = parse_rgba_color(background.get("color", "rgba(0, 0, 0, 0.5)"))
    bg_padding = background.get("padding", 20)
    bg_radius = background.get("radius", 10)
    bg_border_color = parse_rgba_color(background.get("border_color") or "#FFFFFF")
    bg_border_width = background.get("border_width", 0)
    
    # 2. Load Fonts
    try:
        p_font_file = find_font_file(p_font_family, p_bold, p_italic)
        p_font = ImageFont.truetype(p_font_file, p_font_size)
    except:
        p_font = ImageFont.load_default()
        
    try:
        c_font_file = find_font_file(c_font_family, c_bold, c_italic)
        c_font = ImageFont.truetype(c_font_file, c_font_size)
    except:
        c_font = ImageFont.load_default()
        
    # 3. Measure Text
    dummy_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    
    # Get bounding boxes
    p_bbox = dummy_draw.textbbox((0, 0), prefix, font=p_font, stroke_width=p_stroke_width)
    c_bbox = dummy_draw.textbbox((0, 0), channel_name, font=c_font, stroke_width=c_stroke_width)
    
    p_width = p_bbox[2] - p_bbox[0]
    p_height = p_bbox[3] - p_bbox[1]
    
    c_width = c_bbox[2] - c_bbox[0]
    c_height = c_bbox[3] - c_bbox[1]
    
    # Calculate Total Content Size
    space_width = 10 # Default spacing between prefix and channel
    total_text_width = p_width + space_width + c_width
    max_text_height = max(p_height, c_height)
    
    # Canvas Size including Padding and Border
    canvas_width = total_text_width + (bg_padding * 2)
    canvas_height = max_text_height + (bg_padding * 2)
    
    if bg_border_width > 0:
        canvas_width += bg_border_width * 2
        canvas_height += bg_border_width * 2
        
    image = Image.new("RGBA", (int(canvas_width), int(canvas_height)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # 4. Draw Background
    if bg_enabled:
        shape_bounds = [
            bg_border_width / 2, 
            bg_border_width / 2, 
            canvas_width - (bg_border_width / 2), 
            canvas_height - (bg_border_width / 2)
        ]
        
        # Draw fill
        draw.rounded_rectangle(
            xy=[0, 0, canvas_width, canvas_height], # Full size for background
            radius=bg_radius,
            fill=bg_color,
            outline=bg_border_color if bg_border_width > 0 else None,
            width=bg_border_width
        )
    
    # 5. Draw Text
    # Calculate Y positions to center text vertically in the box
    start_x = bg_padding + bg_border_width
    center_y = canvas_height / 2
    
    # Draw Prefix
    # Pillow anchors: la (left, ascender), lm (left, middle), ls (left, baseline)
    # Using 'lm' (Left Middle) makes vertical centering easier
    p_pos = (start_x, center_y)
    draw.text(
        p_pos, 
        prefix, 
        font=p_font, 
        fill=p_color, 
        anchor="lm", 
        stroke_width=p_stroke_width, 
        stroke_fill=p_stroke_color
    )
    
    # Draw Channel
    c_pos = (start_x + p_width + space_width, center_y)
    draw.text(
        c_pos, 
        channel_name, 
        font=c_font, 
        fill=c_color, 
        anchor="lm", 
        stroke_width=c_stroke_width, 
        stroke_fill=c_stroke_color
    )
    
    # Save image
    image.save(output_path, "PNG")
    logger.info(f"Generated overlay image: {output_path} ({image.size})")
    return output_path, image.size


def get_position_coords(position: str, margin_x: int, margin_y: int, overlay_w: int, overlay_h: int) -> str:
    """
    Calculate FFmpeg x:y coordinates for the overlay filter based on image size.
    Returns: "x:y" string
    """
    # W and H are video dimensions, w and h are overlay dimensions
    
    # FFmpeg overlay filter variables:
    # main_w (W), main_h (H) -> Video
    # overlay_w (w), overlay_h (h) -> Overlay Image
    
    # Since we can't easily pass dynamic w/h into a python string without knowing video size,
    # we use FFmpeg's variable names directly.
    
    if position == "top_left":
        return f"{margin_x}:{margin_y}"
    elif position == "top_center":
        return f"(main_w-overlay_w)/2:{margin_y}"
    elif position == "top_right":
        return f"main_w-overlay_w-{margin_x}:{margin_y}"
    elif position == "center_left":
        return f"{margin_x}:(main_h-overlay_h)/2"
    elif position == "center":
        return f"(main_w-overlay_w)/2:(main_h-overlay_h)/2"
    elif position == "center_right":
        return f"main_w-overlay_w-{margin_x}:(main_h-overlay_h)/2"
    elif position == "bottom_left":
        return f"{margin_x}:main_h-overlay_h-{margin_y}"
    elif position == "bottom_center":
        return f"(main_w-overlay_w)/2:main_h-overlay_h-{margin_y}"
    else: # bottom_right
        return f"main_w-overlay_w-{margin_x}:main_h-overlay_h-{margin_y}"


def add_video_source_to_video(
    video_url: str,
    job_id: str,
    channel_name: str,
    prefix: str = "FullVideo:",
    prefix_style: dict = None,
    channel_style: dict = None,
    background: dict = None,
    position: dict = None
) -> dict:
    """
    Add video source overlay to video using PIL generated image and FFmpeg overlay.
    """
    import urllib.request # Late import
    
    # Set defaults
    prefix_style = prefix_style or {}
    channel_style = channel_style or {}
    background = background or {}
    position = position or {}
    
    pos_name = position.get("position", "bottom_right")
    margin_x = position.get("margin_x", 30)
    margin_y = position.get("margin_y", 30)
    
    output_dir = "/app/output"
    input_path = f"{output_dir}/{job_id}_input.mp4"
    overlay_path = f"{output_dir}/{job_id}_overlay.png"
    output_path = f"{output_dir}/{job_id}_output.mp4"
    
    try:
        # 1. Download Video
        download_video_from_url(video_url, input_path)
        
        # 2. Generate Overlay Image
        create_overlay_image(
            prefix, 
            channel_name, 
            prefix_style, 
            channel_style, 
            background, 
            overlay_path
        )
        
        # 3. Calculate Position
        # Note: We rely on FFmpeg expressions for standard positions, 
        # so explicit overlay_w/h aren't strictly needed in Python 
        # unless we were doing manual math.
        overlay_coords = get_position_coords(pos_name, margin_x, margin_y, 0, 0)
        
        # 4. FFmpeg Overlay
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-i", overlay_path,
            "-filter_complex", f"[0:v][1:v]overlay={overlay_coords}[outv]",
            "-map", "[outv]",
            "-map", "0:a?", # Map audio if exists
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "copy",
            output_path
        ]
        
        logger.info(f"Running FFmpeg: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr}")
            raise Exception(f"FFmpeg failed: {result.stderr}")
            
        logger.info(f"Video source overlay added: {output_path}")
        
    finally:
        # Cleanup
        if os.path.exists(input_path):
            os.remove(input_path)
        if os.path.exists(overlay_path):
            os.remove(overlay_path)
            
    return {
        "output_path": output_path,
        "display_text": f"{prefix} {channel_name}"
    }
