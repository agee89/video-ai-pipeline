"""
Thumbnail Generator Module
Generate thumbnails from video with face detection and text overlay.
"""

import cv2
import numpy as np
import mediapipe as mp
import logging
import requests
import os
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

logger = logging.getLogger(__name__)

# Initialize MediaPipe Face Detection
mp_face_detection = mp.solutions.face_detection


def download_image(url: str) -> np.ndarray:
    """Download image from URL and return as numpy array."""
    # Use session with retries and User-Agent
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(max_retries=3)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    response = session.get(url, timeout=30, headers=headers)
    response.raise_for_status()
    image = Image.open(BytesIO(response.content))
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


def find_best_frame(video_path: str, prefer: str = "centered", sample_interval: int = 30) -> np.ndarray:
    """
    Find the best frame from video using face detection.
    
    Args:
        video_path: Path to video file
        prefer: "centered", "largest", or "most_active"
        sample_interval: Check every N frames (default 30 = ~1 per second at 30fps)
    
    Returns:
        Best frame as numpy array
    """
    logger.info(f"[Thumbnail] Finding best frame from {video_path} (prefer={prefer})")
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {video_path}")
    
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    best_frame = None
    best_score = -1
    
    with mp_face_detection.FaceDetection(
        model_selection=1,
        min_detection_confidence=0.5
    ) as face_detector:
        
        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            # Sample every N frames
            if frame_idx % sample_interval != 0:
                frame_idx += 1
                continue
            
            # Convert to RGB for MediaPipe
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = face_detector.process(rgb_frame)
            
            if results.detections:
                for detection in results.detections:
                    bbox = detection.location_data.relative_bounding_box
                    confidence = detection.score[0] if detection.score else 0.5
                    
                    # Calculate face metrics
                    face_cx = bbox.xmin + bbox.width / 2
                    face_cy = bbox.ymin + bbox.height / 2
                    face_size = bbox.width * bbox.height
                    
                    # Score based on preference
                    if prefer == "centered":
                        # Distance from center (0-1, lower is better)
                        dist_from_center = ((face_cx - 0.5) ** 2 + (face_cy - 0.5) ** 2) ** 0.5
                        score = confidence * (1 - dist_from_center) * (1 + face_size)
                    elif prefer == "largest":
                        score = confidence * face_size * 10
                    else:  # most_active or default
                        score = confidence * face_size * (1 + 0.5 * (1 - abs(face_cx - 0.5)))
                    
                    if score > best_score:
                        best_score = score
                        best_frame = frame.copy()
            
            frame_idx += 1
    
    cap.release()
    
    # Fallback: use middle frame if no face found
    if best_frame is None:
        logger.warning("[Thumbnail] No face found, using middle frame")
        cap = cv2.VideoCapture(video_path)
        cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames // 2)
        ret, best_frame = cap.read()
        cap.release()
    
    logger.info(f"[Thumbnail] Best frame found with score {best_score:.3f}")
    return best_frame


def resize_and_crop(image: np.ndarray, target_size: tuple, fit: str = "cover") -> np.ndarray:
    """
    Resize and crop image to target size.
    
    Args:
        image: Input image
        target_size: (width, height)
        fit: "cover" (fill and crop), "contain" (fit inside), "fill" (stretch)
    """
    target_w, target_h = target_size
    src_h, src_w = image.shape[:2]
    
    if fit == "fill":
        # Stretch to fill
        return cv2.resize(image, (target_w, target_h))
    
    elif fit == "contain":
        # Fit inside, add black bars
        scale = min(target_w / src_w, target_h / src_h)
        new_w = int(src_w * scale)
        new_h = int(src_h * scale)
        resized = cv2.resize(image, (new_w, new_h))
        
        # Create black canvas
        canvas = np.zeros((target_h, target_w, 3), dtype=np.uint8)
        x_offset = (target_w - new_w) // 2
        y_offset = (target_h - new_h) // 2
        canvas[y_offset:y_offset+new_h, x_offset:x_offset+new_w] = resized
        return canvas
    
    else:  # cover (default)
        # Fill and crop
        scale = max(target_w / src_w, target_h / src_h)
        new_w = int(src_w * scale)
        new_h = int(src_h * scale)
        resized = cv2.resize(image, (new_w, new_h))
        
        # Center crop
        x_offset = (new_w - target_w) // 2
        y_offset = (new_h - target_h) // 2
        cropped = resized[y_offset:y_offset+target_h, x_offset:x_offset+target_w]
        return cropped


def load_font(font_family: str, font_size: int, font_weight: str = "regular") -> ImageFont.FreeTypeFont:
    """Load font from system or custom fonts directory."""
    
    # FIRST: Try fc-list (fontconfig) to find the font by name
    try:
        import subprocess
        result = subprocess.run(
            ['fc-list', f':family={font_family}', '-f', '%{file}\n'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            font_path = result.stdout.strip().split('\n')[0]
            if os.path.exists(font_path):
                logger.info(f"[Thumbnail] Loaded font via fc-list: {font_path}")
                return ImageFont.truetype(font_path, font_size)
    except Exception as e:
        logger.debug(f"[Thumbnail] fc-list search failed: {e}")
    
    # Font paths to search manually
    font_dirs = [
        "/app/fonts",
        "/usr/share/fonts/truetype/montserrat",
        "/usr/share/fonts/truetype",
        "/usr/share/fonts/truetype/dejavu",
        "/System/Library/Fonts",  # macOS
    ]
    
    # Normalize font family name for matching (remove spaces, lowercase)
    font_family_normalized = font_family.lower().replace(" ", "").replace("-", "").replace("_", "")
    
    # Weight mapping
    weight_map = {
        "bold": ["Bold", "-Bold", "_Bold", ""],
        "regular": ["Regular", "-Regular", "_Regular", ""],
        "light": ["Light", "-Light", "_Light"],
        "medium": ["Medium", "-Medium", "_Medium"],
        "semibold": ["SemiBold", "-SemiBold", "_SemiBold"],
    }
    
    weight_suffixes = weight_map.get(font_weight.lower(), ["Regular", ""])
    
    # First: try exact pattern matches
    for font_dir in font_dirs:
        if not os.path.exists(font_dir):
            continue
        
        for suffix in weight_suffixes:
            patterns = [
                f"{font_family}{suffix}.ttf",
                f"{font_family}-{suffix.replace('-', '')}.ttf" if suffix else f"{font_family}.ttf",
                f"{font_family.lower()}{suffix.lower()}.ttf",
            ]
            
            for pattern in patterns:
                font_path = os.path.join(font_dir, pattern)
                if os.path.exists(font_path):
                    logger.info(f"[Thumbnail] Loaded font: {font_path}")
                    return ImageFont.truetype(font_path, font_size)
    
    # Second: search all .ttf files and do fuzzy matching
    for font_dir in font_dirs:
        if not os.path.exists(font_dir):
            continue
        
        try:
            for filename in os.listdir(font_dir):
                if not filename.lower().endswith('.ttf'):
                    continue
                
                # Normalize filename for matching
                filename_normalized = filename.lower().replace(" ", "").replace("-", "").replace("_", "").replace(".ttf", "")
                
                # Multiple matching strategies:
                # 1. Exact containment
                # 2. First 5+ chars match (handles abbreviations like komikax = komikaaxis)
                # 3. Filename starts with first word of font family
                
                match = False
                
                # Strategy 1: containment
                if font_family_normalized in filename_normalized or filename_normalized in font_family_normalized:
                    match = True
                
                # Strategy 2: first N chars match (min 5 chars)
                min_len = min(len(font_family_normalized), len(filename_normalized))
                if min_len >= 5 and font_family_normalized[:5] == filename_normalized[:5]:
                    match = True
                
                # Strategy 3: first word match
                first_word = font_family.lower().split()[0] if font_family else ""
                if first_word and filename_normalized.startswith(first_word[:5]):
                    match = True
                
                if match:
                    font_path = os.path.join(font_dir, filename)
                    logger.info(f"[Thumbnail] Loaded font (fuzzy match): {font_path}")
                    return ImageFont.truetype(font_path, font_size)
        except Exception as e:
            logger.warning(f"[Thumbnail] Error searching fonts in {font_dir}: {e}")
    
    # Fallback to Montserrat (should be installed)
    logger.warning(f"[Thumbnail] Font '{font_family}' not found, trying Montserrat")
    montserrat_paths = [
        "/usr/share/fonts/truetype/montserrat/Montserrat-Bold.ttf",
        "/usr/share/fonts/truetype/montserrat/Montserrat-Regular.ttf",
    ]
    for path in montserrat_paths:
        if os.path.exists(path):
            logger.info(f"[Thumbnail] Using fallback: {path}")
            return ImageFont.truetype(path, font_size)
    
    # Final fallback to DejaVu
    logger.warning(f"[Thumbnail] Using DejaVuSans fallback with size {font_size}")
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
    except:
        try:
            return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_size)
        except:
            logger.error(f"[Thumbnail] No fonts available, using PIL default")
            return ImageFont.load_default()


def parse_color(color_str: str) -> tuple:
    """Parse color string to RGBA tuple."""
    if color_str.startswith("rgba"):
        # rgba(r, g, b, a)
        parts = color_str.replace("rgba(", "").replace(")", "").split(",")
        r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
        a = int(float(parts[3]) * 255)
        return (r, g, b, a)
    elif color_str.startswith("rgb"):
        parts = color_str.replace("rgb(", "").replace(")", "").split(",")
        return (int(parts[0]), int(parts[1]), int(parts[2]), 255)
    elif color_str.startswith("#"):
        hex_color = color_str.lstrip("#")
        if len(hex_color) == 6:
            return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4)) + (255,)
        elif len(hex_color) == 8:
            return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4, 6))
    
    return (255, 255, 255, 255)  # Default white


def apply_text_overlay(image: np.ndarray, text_config: dict) -> np.ndarray:
    """
    Apply text overlay to image using Pillow.
    Text will be wrapped to fit within frame width with proper padding.
    
    Args:
        image: Input image (BGR numpy array)
        text_config: Text overlay configuration dict
    """
    # Convert to PIL Image (RGB)
    pil_image = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    
    # Create overlay with alpha
    overlay = Image.new("RGBA", pil_image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    
    # Extract config
    text = text_config.get("text", "")
    style = text_config.get("style", {})
    bg_config = text_config.get("background", {})
    position = text_config.get("position", {})
    
    # Apply text transform
    text_transform = style.get("text_transform")
    if text_transform == "uppercase":
        text = text.upper()
    elif text_transform == "lowercase":
        text = text.lower()
    elif text_transform == "capitalize":
        text = text.title()
    
    # Load font
    font_family = style.get("font_family", "Montserrat")
    font_size = style.get("font_size", 100)
    font_weight = style.get("font_weight", "bold")
    font = load_font(font_family, font_size, font_weight)
    
    # Image dimensions and edge padding (configurable)
    img_w, img_h = pil_image.size
    edge_padding = position.get("edge_padding", 60)  # Configurable from API
    bg_padding = bg_config.get("padding", 40) if bg_config.get("enabled", True) else 0
    
    # Parse text shadow (format: "2px 2px 4px #000000")
    text_shadow = style.get("text_shadow")
    shadow_offset_x = 0
    shadow_offset_y = 0
    shadow_blur = 0
    shadow_color = None
    
    if text_shadow:
        try:
            parts = text_shadow.replace("px", "").split()
            if len(parts) >= 4:
                shadow_offset_x = int(parts[0])
                shadow_offset_y = int(parts[1])
                shadow_blur = int(parts[2])
                shadow_color = parse_color(parts[3])
            elif len(parts) == 3:
                shadow_offset_x = int(parts[0])
                shadow_offset_y = int(parts[1])
                shadow_color = parse_color(parts[2])
        except:
            logger.warning(f"[Thumbnail] Could not parse text_shadow: {text_shadow}")
    
    # Calculate max text width - use more of the available space
    # Edge padding is minimum from edge, bg_padding is inside the box
    available_width = img_w - (edge_padding * 2)
    max_text_width = available_width - (bg_padding * 2)
    
    # Get max_lines from position config (default 3)
    max_lines = position.get("max_lines", 3)
    
    # Wrap text if needed
    words = text.split()
    lines = []
    current_line = ""
    
    for word in words:
        test_line = f"{current_line} {word}".strip()
        bbox = draw.textbbox((0, 0), test_line, font=font)
        line_width = bbox[2] - bbox[0]
        
        if line_width <= max_text_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
            
            # Stop if we've reached max lines
            if len(lines) >= max_lines:
                # Truncate remaining text
                if current_line:
                    lines[-1] = lines[-1] + "..."
                current_line = ""
                break
    
    if current_line and len(lines) < max_lines:
        lines.append(current_line)
    
    # Calculate actual line height using font metrics
    # Use textbbox to get real height of text - sample_bbox[1] is the y-offset (can be negative)
    sample_bbox = draw.textbbox((0, 0), "Ag", font=font)  # Use chars with ascender/descender
    text_y_offset = sample_bbox[1]  # This is the offset from y=0 to actual top of text
    actual_line_height = sample_bbox[3] - sample_bbox[1]
    
    # Get line_spacing from style config
    # Priority: line_spacing (pixels) > line_height (multiplier) > default (15% of font_size)
    config_line_spacing = style.get("line_spacing")
    config_line_height = style.get("line_height")
    
    if config_line_spacing is not None:
        # Use pixel value directly
        line_spacing = int(config_line_spacing)
    elif config_line_height is not None:
        # Use multiplier (e.g. 1.2 = 20% extra spacing)
        line_spacing = int(font_size * (config_line_height - 1.0))
    else:
        # Default: 15% of font_size
        line_spacing = int(font_size * 0.15)
    
    line_height = actual_line_height + line_spacing
    
    # Calculate total text block height
    # For first line, use full height; for additional lines, add spacing
    if len(lines) > 0:
        total_text_height = actual_line_height + (len(lines) - 1) * line_height
    else:
        total_text_height = 0
    
    # Find max line width for background box
    max_line_width = 0
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        max_line_width = max(max_line_width, bbox[2] - bbox[0])
    
    # Y position - default higher on screen
    y_pos = position.get("y", "bottom")
    margin_top = position.get("margin_top", 0)
    margin_bottom = position.get("margin_bottom", 250)  # Higher default
    
    if y_pos == "top":
        y_start = margin_top + edge_padding + bg_padding
    elif y_pos == "center":
        y_start = (img_h - total_text_height) // 2
    elif y_pos == "bottom":
        y_start = img_h - total_text_height - margin_bottom - bg_padding
    else:
        y_start = int(y_pos)
    
    # X position for center alignment
    x_pos = position.get("x", "center")
    
    # Draw background box (covers all lines) - only if enabled
    bg_enabled = bg_config.get("enabled", True)
    if bg_enabled:
        bg_color_tuple = parse_color(bg_config.get("color", "rgba(0,0,0,0.7)"))
        radius = bg_config.get("radius", 20)
        full_width = bg_config.get("full_width", True)  # Default: 100% width
        gradient = bg_config.get("gradient", False)  # Enable gradient mode
        gradient_height = bg_config.get("gradient_height", 0)  # Custom height or auto
        
        # Calculate box coordinates
        if full_width:
            box_x1 = 0
            box_x2 = img_w
        elif x_pos == "center":
            box_x1 = (img_w - max_line_width) // 2 - bg_padding
            box_x2 = box_x1 + max_line_width + bg_padding * 2
        elif x_pos == "left":
            box_x1 = edge_padding
            box_x2 = box_x1 + max_line_width + bg_padding * 2
        else:
            box_x1 = img_w - max_line_width - edge_padding - bg_padding * 2
            box_x2 = box_x1 + max_line_width + bg_padding * 2
        
        # Calculate Y coordinates
        box_y1 = y_start + text_y_offset - bg_padding
        box_y2 = y_start + text_y_offset + total_text_height + bg_padding
        
        if gradient:
            # GRADIENT MODE: From bottom (solid) to top (transparent)
            # Height: from bottom of image to above text, or custom height
            grad_bottom = img_h  # Start from very bottom
            
            if gradient_height > 0:
                grad_top = img_h - gradient_height
            else:
                # Auto: extend to above the text with extra space
                grad_top = max(0, box_y1 - 100)  # 100px above text
            
            grad_height = grad_bottom - grad_top
            
            # Draw gradient line by line
            for y in range(int(grad_top), int(grad_bottom)):
                # Calculate alpha: 0 at top, full at bottom
                progress = (y - grad_top) / grad_height if grad_height > 0 else 1
                alpha = int(bg_color_tuple[3] * progress)
                
                line_color = (bg_color_tuple[0], bg_color_tuple[1], bg_color_tuple[2], alpha)
                draw.line([(box_x1, y), (box_x2, y)], fill=line_color)
        else:
            # SOLID MODE: Normal rounded rectangle
            if not full_width:
                box_x1 = max(edge_padding, box_x1)
                box_x2 = min(img_w - edge_padding, box_x2)
            box_y1 = max(0, box_y1)
            box_y2 = min(img_h, box_y2)
            
            draw.rounded_rectangle(
                [box_x1, box_y1, box_x2, box_y2],
                radius=radius,
                fill=bg_color_tuple
            )
    
    # Get letter spacing
    letter_spacing = style.get("letter_spacing", 0) or 0
    
    # Helper function to draw text with letter spacing
    def draw_text_with_spacing(draw_obj, pos, text, font, fill, spacing=0, stroke_width=0, stroke_fill=None):
        if spacing == 0:
            # Normal drawing
            if stroke_width > 0 and stroke_fill:
                draw_obj.text(pos, text, font=font, fill=stroke_fill, stroke_width=stroke_width)
            draw_obj.text(pos, text, font=font, fill=fill)
        else:
            # Character by character with spacing
            x, y = pos
            for char in text:
                if stroke_width > 0 and stroke_fill:
                    draw_obj.text((x, y), char, font=font, fill=stroke_fill, stroke_width=stroke_width)
                draw_obj.text((x, y), char, font=font, fill=fill)
                char_bbox = draw_obj.textbbox((0, 0), char, font=font)
                char_width = char_bbox[2] - char_bbox[0]
                x += char_width + spacing
    
    # Helper to calculate line width with letter spacing
    def get_line_width_with_spacing(text, font, spacing=0):
        if spacing == 0:
            bbox = draw.textbbox((0, 0), text, font=font)
            return bbox[2] - bbox[0]
        else:
            total_width = 0
            for i, char in enumerate(text):
                char_bbox = draw.textbbox((0, 0), char, font=font)
                char_width = char_bbox[2] - char_bbox[0]
                total_width += char_width
                if i < len(text) - 1:
                    total_width += spacing
            return total_width
    
    # Draw each line of text
    text_color = parse_color(style.get("color", "#FFFFFF"))
    stroke_color_val = style.get("stroke_color")
    stroke_width = style.get("stroke_width", 0)
    stroke_rgba = parse_color(stroke_color_val) if stroke_color_val else None
    
    for i, line in enumerate(lines):
        line_width = get_line_width_with_spacing(line, font, letter_spacing)
        
        # X position for this line
        if x_pos == "center":
            x = (img_w - line_width) // 2
        elif x_pos == "left":
            x = edge_padding + bg_padding
        elif x_pos == "right":
            x = img_w - line_width - edge_padding - bg_padding
        else:
            x = int(x_pos)
        
        y = y_start + i * line_height
        
        # Draw text shadow (if configured)
        if shadow_color:
            if letter_spacing == 0:
                draw.text(
                    (x + shadow_offset_x, y + shadow_offset_y), 
                    line, 
                    font=font, 
                    fill=shadow_color
                )
            else:
                # Draw shadow char by char
                sx = x + shadow_offset_x
                for char in line:
                    draw.text((sx, y + shadow_offset_y), char, font=font, fill=shadow_color)
                    char_bbox = draw.textbbox((0, 0), char, font=font)
                    sx += char_bbox[2] - char_bbox[0] + letter_spacing
        
        # Draw main text (with stroke if configured)
        draw_text_with_spacing(
            draw, (x, y), line, font, text_color, 
            spacing=letter_spacing, 
            stroke_width=stroke_width, 
            stroke_fill=stroke_rgba
        )
    
    # Composite overlay onto image
    pil_image = pil_image.convert("RGBA")
    result = Image.alpha_composite(pil_image, overlay)
    result = result.convert("RGB")
    
    return cv2.cvtColor(np.array(result), cv2.COLOR_RGB2BGR)


def generate_thumbnail(
    video_path: str = None,
    output_path: str = None,
    size: str = "1080x1920",
    frame_selection: dict = None,
    background_image: dict = None,
    text_overlay: dict = None,
    export_settings: dict = None
) -> str:
    """
    Generate thumbnail from video with text overlay.
    
    Args:
        video_path: Path to source video
        output_path: Path for output image
        size: Output size "WxH"
        frame_selection: Frame selection config
        background_image: Background image override config
        text_overlay: Text overlay config
        export_settings: Export format settings
    
    Returns:
        Path to generated thumbnail
    """
    logger.info(f"[Thumbnail] Generating thumbnail: {size}")
    
    # Parse size
    target_w, target_h = map(int, size.lower().split("x"))
    target_size = (target_w, target_h)
    
    # Get base image
    if background_image and background_image.get("url"):
        # Use provided background image
        logger.info(f"[Thumbnail] Using background image: {background_image['url']}")
        base_image = download_image(background_image["url"])
        fit = background_image.get("fit", "cover")
    elif video_path:
        # Extract frame from video
        frame_config = frame_selection or {}
        prefer = frame_config.get("prefer", "centered")
        
        if frame_config.get("mode") == "timestamp" and frame_config.get("timestamp"):
            # Extract specific frame
            timestamp = frame_config["timestamp"]
            base_image = extract_frame_at_timestamp(video_path, timestamp)
        else:
            # Face detection mode
            base_image = find_best_frame(video_path, prefer=prefer)
        
        fit = "cover"
    else:
        raise ValueError("Either video_path or background_image.url is required")
    
    # Resize and crop to target size
    base_image = resize_and_crop(base_image, target_size, fit)
    
    # Apply text overlay
    if text_overlay:
        base_image = apply_text_overlay(base_image, text_overlay)
    
    # Export
    export = export_settings or {}
    format_type = export.get("format", "png").lower()
    quality = export.get("quality", 95)
    
    # Ensure output path has correct extension
    if output_path:
        base_name = os.path.splitext(output_path)[0]
        output_path = f"{base_name}.{format_type}"
    else:
        output_path = f"/app/output/thumbnail.{format_type}"
    
    # Save image
    if format_type == "png":
        cv2.imwrite(output_path, base_image)
    elif format_type in ["jpg", "jpeg"]:
        cv2.imwrite(output_path, base_image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    elif format_type == "webp":
        cv2.imwrite(output_path, base_image, [cv2.IMWRITE_WEBP_QUALITY, quality])
    else:
        cv2.imwrite(output_path, base_image)
    
    logger.info(f"[Thumbnail] Saved: {output_path}")
    return output_path


def extract_frame_at_timestamp(video_path: str, timestamp: str) -> np.ndarray:
    """Extract frame at specific timestamp (format: MM:SS or HH:MM:SS)."""
    parts = timestamp.split(":")
    if len(parts) == 2:
        seconds = int(parts[0]) * 60 + int(parts[1])
    elif len(parts) == 3:
        seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    else:
        seconds = int(parts[0])
    
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    frame_number = int(seconds * fps)
    
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
    ret, frame = cap.read()
    cap.release()
    
    if not ret:
        raise ValueError(f"Cannot extract frame at timestamp {timestamp}")
    
    return frame
