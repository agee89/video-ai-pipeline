"""
Captioner Module - Add captions to video using Whisper for transcription

Features:
- Whisper transcription with Indonesian support
- Word-level highlighting (karaoke style)
- Customizable styling (font, color, position, etc.)
- ASS subtitle format for rich styling
"""

import subprocess
import os
import logging
import sys
import tempfile
import urllib.request
import requests
import re
from typing import Optional, Dict, Any

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("captioner")

# Position mapping to ASS alignment
POSITION_MAP = {
    "top_left": 7,
    "top_center": 8,
    "top_right": 9,
    "middle_left": 4,
    "middle_center": 5,
    "middle_right": 6,
    "bottom_left": 1,
    "bottom_center": 2,
    "bottom_right": 3
}

def hex_to_ass_color(hex_color: str) -> str:
    """Convert hex color (#RRGGBB) to ASS format (&HBBGGRR&)"""
    hex_color = hex_color.lstrip('#')
    r, g, b = hex_color[0:2], hex_color[2:4], hex_color[4:6]
    return f"&H{b}{g}{r}&"


def download_video_from_url(url: str, output_path: str) -> str:
    """Download video from URL (MinIO or external)"""
    internal_url = url
    
    # Handle hostname conflicts (Same as video_source.py):
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
    
    logger.info(f"[Caption] Downloading video from (internal): {internal_url}")
    
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
                
        logger.info(f"[Caption] Downloaded to: {output_path}")
        return output_path
    except Exception as e:
        logger.error(f"[Caption] Download failed for {internal_url}: {e}")
        raise Exception(f"Failed to download video: {e}")


def extract_audio(video_path: str, audio_path: str) -> str:
    """Extract audio from video for Whisper transcription"""
    logger.info("[Caption] Extracting audio...")
    
    cmd = [
        'ffmpeg', '-y', '-i', video_path,
        '-vn', '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1',
        audio_path
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"Audio extraction failed: {result.stderr}")
    
    logger.info(f"[Caption] Audio extracted: {audio_path}")
    return audio_path


def transcribe_with_whisper(audio_path: str, language: str = "id", model_name: str = "medium") -> Dict:
    """Transcribe audio using Whisper with word-level timestamps"""
    logger.info(f"[Caption] Transcribing with Whisper (language={language}, model={model_name})...")
    
    try:
        import whisper
    except ImportError:
        raise Exception("Whisper not installed. Run: pip install openai-whisper")
    
    # Validate model name
    valid_models = ["tiny", "base", "small", "medium", "large"]
    if model_name not in valid_models:
        logger.warning(f"[Caption] Invalid model '{model_name}', using 'medium'")
        model_name = "medium"
    
    logger.info(f"[Caption] Loading Whisper '{model_name}' model...")
    model = whisper.load_model(model_name)
    
    # Transcribe with word timestamps
    logger.info("[Caption] Transcribing audio...")
    result = model.transcribe(
        audio_path,
        language=language,
        word_timestamps=True,
        verbose=False
    )
    
    logger.info(f"[Caption] Transcription complete: {len(result['segments'])} segments")
    return result


def generate_ass_subtitle(
    transcription: Dict,
    output_path: str,
    settings: Dict[str, Any]
) -> str:
    """Generate ASS subtitle file with word-level highlighting"""
    
    # Extract settings with defaults
    font_family = settings.get("font_family", "Montserrat")
    font_size = settings.get("font_size", 60)
    line_color = settings.get("line_color", "#FFFFFF")
    word_color = settings.get("word_color", "#FFDD5C")
    all_caps = settings.get("all_caps", True)
    max_words = settings.get("max_words_per_line", 3)
    bold = settings.get("bold", True)
    italic = settings.get("italic", False)
    outline_width = settings.get("outline_width", 3)
    outline_color = settings.get("outline_color", "#000000")
    shadow_offset = settings.get("shadow_offset", 2)
    position = settings.get("position", "bottom_center")
    margin_v = settings.get("margin_v", 640)  # Default distance from edge
    
    # Determine alignment from position
    alignment = POSITION_MAP.get(position, 2)  # Default to bottom_center (2)
    
    logger.info(f"[Caption] Style: font={font_family}, size={font_size}, margin_v={margin_v}, alignment={alignment}")
    
    # Convert colors
    ass_line_color = hex_to_ass_color(line_color)
    ass_word_color = hex_to_ass_color(word_color)
    ass_outline_color = hex_to_ass_color(outline_color)
    
    # Font style
    bold_val = -1 if bold else 0
    italic_val = -1 if italic else 0
    
    # ASS header
    ass_content = f"""[Script Info]
Title: Auto Caption
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_family},{font_size},{ass_line_color},&H000000FF,{ass_outline_color},&H80000000,{bold_val},{italic_val},0,0,100,100,0,0,1,{outline_width},{shadow_offset},{alignment},50,50,{margin_v},1
Style: Highlight,{font_family},{font_size},{ass_word_color},&H000000FF,{ass_outline_color},&H80000000,{bold_val},{italic_val},0,0,100,100,0,0,1,{outline_width},{shadow_offset},{alignment},50,50,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    
    def format_time(seconds: float) -> str:
        """Convert seconds to ASS time format (h:mm:ss.cc)"""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = seconds % 60
        return f"{h}:{m:02d}:{s:05.2f}"
    
    # Process segments and words
    for segment in transcription.get("segments", []):
        words = segment.get("words", [])
        
        if not words:
            # No word-level timestamps, use segment text
            text = segment["text"].strip()
            if all_caps:
                text = text.upper()
            
            start = format_time(segment["start"])
            end = format_time(segment["end"])
            ass_content += f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n"
            continue
        
        # Group words into lines
        word_groups = []
        current_group = []
        
        for word in words:
            current_group.append(word)
            if len(current_group) >= max_words:
                word_groups.append(current_group)
                current_group = []
        
        if current_group:
            word_groups.append(current_group)
        
        # Generate dialogue lines with word-by-word highlighting
        for group in word_groups:
            if not group:
                continue
            
            group_start = group[0]["start"]
            group_end = group[-1]["end"]
            
            # Create highlighted text for each word timing
            for i, target_word in enumerate(group):
                word_start = target_word["start"]
                word_end = target_word["end"]
                
                # Build text with current word highlighted
                text_parts = []
                for j, word in enumerate(group):
                    word_text = word["word"].strip()
                    if all_caps:
                        word_text = word_text.upper()
                    
                    if j == i:
                        # Highlight current word
                        text_parts.append(f"{{\\rHighlight}}{word_text}{{\\rDefault}}")
                    else:
                        text_parts.append(word_text)
                
                line_text = " ".join(text_parts)
                
                start_time = format_time(word_start)
                end_time = format_time(word_end)
                
                ass_content += f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{line_text}\n"
    
    # Write ASS file
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(ass_content)
    
    logger.info(f"[Caption] ASS subtitle generated: {output_path}")
    return output_path


def burn_subtitles(video_path: str, subtitle_path: str, output_path: str, font_dir: str = None) -> str:
    """Burn ASS subtitles into video using FFmpeg"""
    logger.info("[Caption] Burning subtitles into video...")
    
    # Build filter with optional font directory
    subtitle_filter = f"ass={subtitle_path}"
    if font_dir and os.path.exists(font_dir):
        subtitle_filter = f"ass={subtitle_path}:fontsdir={font_dir}"
    
    cmd = [
        'ffmpeg', '-y',
        '-i', video_path,
        '-vf', subtitle_filter,
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
        '-c:a', 'aac', '-b:a', '192k',
        '-movflags', '+faststart',
        output_path
    ]
    
    logger.info(f"[Caption] Running FFmpeg...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        raise Exception(f"FFmpeg subtitle burn failed: {result.stderr[-500:]}")
    
    logger.info(f"[Caption] Output video: {output_path}")
    return output_path


def add_captions_to_video(
    video_url: str,
    job_id: str,
    language: str = "id",
    model: str = "medium",
    settings: Dict[str, Any] = None
) -> Dict[str, str]:
    """
    Main function to add captions to a video
    
    Args:
        video_url: URL of the source video
        job_id: Unique job identifier
        language: Language code for Whisper (default: "id" for Indonesian)
        settings: Caption styling settings
    
    Returns:
        Dict with output paths and transcript
    """
    import traceback
    
    if settings is None:
        settings = {}
    
    output_dir = "/app/output"
    os.makedirs(output_dir, exist_ok=True)
    
    # Temp files
    video_path = f"{output_dir}/{job_id}_source.mp4"
    audio_path = f"{output_dir}/{job_id}_audio.wav"
    subtitle_path = f"{output_dir}/{job_id}.ass"
    output_path = f"{output_dir}/{job_id}_captioned.mp4"
    
    try:
        # Step 1: Download video
        download_video_from_url(video_url, video_path)
        
        # Step 2: Extract audio
        extract_audio(video_path, audio_path)
        
        # Step 3: Transcribe with Whisper
        transcription = transcribe_with_whisper(audio_path, language, model)
        
        # Get full transcript text
        full_transcript = " ".join([s["text"].strip() for s in transcription.get("segments", [])])
        
        # Step 4: Generate ASS subtitle
        generate_ass_subtitle(transcription, subtitle_path, settings)
        
        # Step 5: Burn subtitles into video
        burn_subtitles(video_path, subtitle_path, output_path)
        
        # Cleanup temp files
        for temp_file in [video_path, audio_path, subtitle_path]:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        
        logger.info(f"[Caption] Complete: {output_path}")
        
        return {
            "output_path": output_path,
            "transcript": full_transcript
        }
        
    except Exception as e:
        logger.error(f"[Caption] Failed: {e}")
        logger.error(traceback.format_exc())
        
        # Cleanup on error
        for temp_file in [video_path, audio_path, subtitle_path]:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass
        
        raise
