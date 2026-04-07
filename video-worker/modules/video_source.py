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
    Find font file path using robust strategy mirrored from thumbnail.py.
    """
    font_weight = "bold" if bold else "regular"
    if italic:
        # Simple mapping for now, assuming bold takes precedence if both true
        pass 

    # 1. Try fc-list (fontconfig) first
    try:
        query = f":family={font_family}"
        if bold:
            query += ":style=Bold"
        elif italic:
            query += ":style=Italic"
            
        result = subprocess.run(
            ['fc-list', query, '-f', '%{file}\\n'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            font_paths = result.stdout.strip().split('\n')
            for font_path in font_paths:
                if os.path.exists(font_path):
                    logger.info(f"Font found via fc-list: {font_path}")
                    return font_path
    except Exception as e:
        logger.debug(f"fc-list search failed: {e}")
    
    # 2. Manual Search in known directories
    font_dirs = [
        "/app/fonts",
        "/usr/share/fonts/truetype",
        "/usr/share/fonts/truetype/dejavu",
        "/usr/share/fonts/truetype/montserrat",
    ]
    
    # Normalize input
    font_family_normalized = font_family.lower().replace(" ", "").replace("-", "").replace("_", "")
    
    # Weight suffixes
    weight_suffixes = [""]
    if bold:
        weight_suffixes = ["Bold", "-Bold", "_Bold", ""]
    elif italic:
        weight_suffixes = ["Italic", "-Italic", "_Italic", ""]
    else:
        weight_suffixes = ["Regular", "-Regular", "_Regular", ""]

    # 2a. Exact/Pattern Match
    for font_dir in font_dirs:
        if not os.path.exists(font_dir):
            continue
            
        for suffix in weight_suffixes:
            patterns = [
                f"{font_family}{suffix}.ttf",
                f"{font_family}{suffix}.otf",
                f"{font_family}-{suffix.replace('-', '')}.ttf" if suffix else f"{font_family}.ttf",
                f"{font_family.lower()}{suffix.lower()}.ttf",
            ]
            
            for pattern in patterns:
                font_path = os.path.join(font_dir, pattern)
                if os.path.exists(font_path):
                    logger.info(f"Font found by pattern: {font_path}")
                    return font_path

    # 2b. Fuzzy Match (The "thumbnail.py" magic)
    for font_dir in font_dirs:
        if not os.path.exists(font_dir):
            continue
            
        try:
            for filename in os.listdir(font_dir):
                if not filename.lower().endswith(('.ttf', '.otf')):
                    continue
                
                # Normalize filename
                filename_normalized = filename.lower().replace(" ", "").replace("-", "").replace("_", "").replace(".ttf", "").replace(".otf", "")
                
                match = False
                
                # Strategy 1: containment
                if font_family_normalized in filename_normalized or filename_normalized in font_family_normalized:
                    match = True
                
                # Strategy 2: First 5+ chars match (e.g. komikax matches komikaaxis)
                min_len = min(len(font_family_normalized), len(filename_normalized))
                if min_len >= 5 and font_family_normalized[:5] == filename_normalized[:5]:
                    match = True
                
                # Strategy 3: First word match
                first_word = font_family.lower().split()[0] if font_family else ""
                if first_word and len(first_word) >= 4 and filename_normalized.startswith(first_word):
                    match = True
                
                if match:
                    font_path = os.path.join(font_dir, filename)
                    logger.info(f"Font found by fuzzy match: {font_path}")
                    return font_path

        except Exception as e:
            continue

    # 3. Last Resort Fallback
    logger.warning(f"Font {font_family} not found. Using default.")
    return "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def create_overlay_image(
    prefix: str,
    channel_name: str,
    prefix_style: dict,
    channel_style: dict,
    output_path: str,
    logo_path: str = None,
    logo_scale: float = 1.0,
    line_spacing: int = 8,
    logo_offset_y: int = 0,
    logo_spacing: int = 10
):
    """Generates the overlay image using Pillow (No Background)"""
    
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
    
    # 2. Load Fonts
    # ... (Fonts loading is identical)
    # Prefix Font
    try:
        p_font_file = find_font_file(p_font_family, p_bold, p_italic)
        logger.info(f"Prefix font resolved to: {p_font_file}")
        try:
            p_font = ImageFont.truetype(p_font_file, p_font_size)
        except Exception as e:
            logger.error(f"Failed to load prefix font {p_font_file}: {e}")
            p_font = ImageFont.load_default()
    except Exception as e:
        logger.error(f"Error finding prefix font {p_font_family}: {e}")
        p_font = ImageFont.load_default()
        
    # Channel Font
    try:
        c_font_file = find_font_file(c_font_family, c_bold, c_italic)
        logger.info(f"Channel font resolved to: {c_font_file}")
        try:
            c_font = ImageFont.truetype(c_font_file, c_font_size)
        except Exception as e:
            logger.error(f"Failed to load channel font {c_font_file}: {e}")
            c_font = ImageFont.load_default()
    except Exception as e:
        logger.error(f"Error finding channel font {c_font_family}: {e}")
        c_font = ImageFont.load_default()
        
    # 3. Measure Text
    dummy_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    
    # Get bounding boxes
    p_bbox = dummy_draw.textbbox((0, 0), prefix, font=p_font, stroke_width=p_stroke_width, anchor="lt")
    c_bbox = dummy_draw.textbbox((0, 0), channel_name, font=c_font, stroke_width=c_stroke_width, anchor="lt")
    
    p_width = p_bbox[2] - p_bbox[0]
    p_height = p_bbox[3] - p_bbox[1]
    
    c_width = c_bbox[2] - c_bbox[0]
    c_height = c_bbox[3] - c_bbox[1]
    
    # Stacked Layout Logic
    text_block_width = max(p_width, c_width)
    text_block_height = p_height + line_spacing + c_height
    
    # 4. Prepare Logo
    logo_img = None
    logo_w, logo_h = 0, 0
    
    if logo_path and os.path.exists(logo_path):
        try:
            logo_raw = Image.open(logo_path).convert("RGBA")
            
            # Target height = text_block_height * scale
            target_h = int(text_block_height * logo_scale)
            if target_h < 10: target_h = 10 # Minimum safe size
            
            # Maintain aspect ratio
            aspect = logo_raw.width / logo_raw.height
            target_w = int(target_h * aspect)
            
            logo_img = logo_raw.resize((target_w, target_h), Image.Resampling.LANCZOS)
            logo_w = target_w
            logo_h = target_h
            logger.info(f"Loaded logo: {logo_w}x{logo_h}")
        except Exception as e:
            logger.error(f"Failed to load logo image: {e}")

    # 5. Calculate Layout Dimensions
    # Layout Model: [Logo] [Spacing] [Text]
    # No padding, no border
    
    # Text Box Size (Content Only)
    text_box_w = text_block_width
    text_box_h = text_block_height
    
    # Total Canvas Size
    canvas_w = text_box_w
    if logo_img:
        canvas_w += logo_w + logo_spacing
        
    # Height is max of Logo or Text Box
    canvas_h = max(text_box_h, logo_h)
    
    # 6. Create Canvas
    img = Image.new("RGBA", (int(canvas_w), int(canvas_h)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Vertical Centering Offsets
    center_y = canvas_h // 2
    
    # 7. Draw Content
    # Draw Logo
    if logo_img:
        logo_y = center_y - (logo_h // 2) + logo_offset_y
        
        # Use alpha_composite for safer transparency blending
        # Note: alpha_composite requires both images to be same size, 
        # allow pasting at offset we need a temp layer or just use paste with care.
        # Actually paste(src, mask=src) is correct for RGBA onto RGBA.
        # But let's verify if the logo has proper alpha.
        
        # Alternative: Create a temp layer for the logo and alpha_composite it
        logo_layer = Image.new("RGBA", (canvas_w, canvas_h), (0,0,0,0))
        logo_layer.paste(logo_img, (0, int(logo_y)))
        
        img = Image.alpha_composite(img, logo_layer)
        
        # Re-create draw object because img reference changed
        draw = ImageDraw.Draw(img)
        
    # Draw Text
    # Calculate Text Block Origin inside the Background Box
    # Background Box Start X
    bg_start_x = 0
    if logo_img:
        bg_start_x = logo_w + logo_spacing
        
    # Text starts at BG Start (no padding)
    text_start_x = bg_start_x
    
    # Text Block Vertical Center
    text_block_start_y = center_y - (text_block_height // 2)
    
    # Draw Prefix
    draw.text(
        (text_start_x, text_block_start_y),  
        prefix, 
        font=p_font, 
        fill=p_color, 
        stroke_width=p_stroke_width, 
        stroke_fill=p_stroke_color,
        anchor="lt" # Explicitly use left-top anchor
    )
    
    # Channel (Line 2)
    c_y = text_block_start_y + p_height + line_spacing
    draw.text(
        (text_start_x, c_y), 
        channel_name, 
        font=c_font, 
        fill=c_color, 
        stroke_width=c_stroke_width, 
        stroke_fill=c_stroke_color,
        anchor="lt" # Explicitly use left-top anchor
    )
    
    # Save image
    img.save(output_path)
    logger.info(f"Generated overlay image: {output_path} ({canvas_w}x{canvas_h})")
    
    return output_path, (canvas_w, canvas_h)


def parse_margin(margin: str | int, dimension_var: str) -> str:
    """
    Parse margin value into FFmpeg expression.
    - int or numeric string -> return as is (pixels)
    - "N%" -> return "dimension_var * N/100"
    """
    if isinstance(margin, int):
        return str(margin)
    
    margin_str = str(margin).strip().lower()
    
    if margin_str.endswith('%'):
        try:
            val = float(margin_str[:-1])
            return f"{dimension_var}*{val/100}"
        except ValueError:
            return "0"
            
    return margin_str

def get_position_coords(position: str, margin_x: str | int, margin_y: str | int, overlay_w: int, overlay_h: int) -> str:
    """
    Calculate FFmpeg x:y coordinates for the overlay filter based on image size.
    Returns: "x:y" string
    """
    # Parse margins into expressions
    mx = parse_margin(margin_x, "main_w")
    my = parse_margin(margin_y, "main_h")
    
    # W and H are video dimensions, w and h are overlay dimensions
    
    # FFmpeg overlay filter variables:
    # main_w (W), main_h (H) -> Video
    # overlay_w (w), overlay_h (h) -> Overlay Image
    
    # Since we can't easily pass dynamic w/h into a python string without knowing video size,
    # we use FFmpeg's variable names directly.
    
    if position == "top_left":
        return f"{mx}:{my}"
    elif position == "top_center":
        return f"(main_w-overlay_w)/2:{my}"
    elif position == "top_right":
        return f"main_w-overlay_w-{mx}:{my}"
    elif position == "center_left":
        return f"{mx}:(main_h-overlay_h)/2"
    elif position == "center":
        return f"(main_w-overlay_w)/2:(main_h-overlay_h)/2"
    elif position == "center_right":
        return f"main_w-overlay_w-{mx}:(main_h-overlay_h)/2"
    elif position == "bottom_left":
        return f"{mx}:main_h-overlay_h-{my}"
    elif position == "bottom_center":
        return f"(main_w-overlay_w)/2:main_h-overlay_h-{my}"
    elif position == "bottom_right":
        return f"main_w-overlay_w-{mx}:main_h-overlay_h-{my}"
    else: # bottom_right
        # Default fallback to bottom_right
        return f"main_w-overlay_w-{mx}:main_h-overlay_h-{my}"


def add_video_source_to_video(
    video_url: str,
    job_id: str,
    channel_name: str,
    prefix: str = "Source:",
    prefix_style: dict = None,
    channel_style: dict = None,
    position: dict = None,
    logo_url: str = None,
    logo_scale: float = 1.0,
    line_spacing: int = 8,
    logo_offset_y: int = 0,
    logo_spacing: int = 10
) -> dict:
    """
    Add video source overlay to video.
    """
    import urllib.request # Late import
    
    prefix_style = prefix_style or {}
    channel_style = channel_style or {}
    position = position or {}
    
    # Prepare paths
    output_dir = "/app/output"
    input_path = f"{output_dir}/{job_id}_input.mp4"
    overlay_path = f"{output_dir}/{job_id}_overlay.png"
    output_path = f"{output_dir}/{job_id}_output.mp4"
    logo_path = None
    
    try:
        # 1. Download Video
        download_video_from_url(video_url, input_path)
        
        # 2. Download logo if provided
        if logo_url:
            logo_path = f"{output_dir}/{job_id}_logo.png"
            try:
                download_video_from_url(logo_url, logo_path) # reusing download function
            except Exception as e:
                logger.error(f"Failed to download logo: {e}")
                logo_path = None
        
        # 3. Generate Overlay Image
        overlay_output_path, overlay_size = create_overlay_image(
            prefix, 
            channel_name, 
            prefix_style, 
            channel_style, 
            overlay_path,
            logo_path=logo_path,
            logo_scale=logo_scale,
            line_spacing=line_spacing,
            logo_offset_y=logo_offset_y,
            logo_spacing=logo_spacing
        )
        
        # 4. Calculate Position
        pos_name = position.get("position", "bottom_right")
        margin_x = position.get("margin_x", 30)
        margin_y = position.get("margin_y", 30)
        
        # Note: We rely on FFmpeg expressions for standard positions, 
        # so explicit overlay_w/h aren't strictly needed in Python 
        # unless we were doing manual math.
        overlay_coords = get_position_coords(pos_name, margin_x, margin_y, 0, 0)
        
        # 5. FFmpeg Overlay
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-i", overlay_output_path,
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
        if logo_path and os.path.exists(logo_path):
            os.remove(logo_path)
            
    return {
        "output_path": output_path,
        "display_text": f"{prefix} {channel_name}"
    }
