import subprocess
import json
import math
from typing import Dict, Any, Optional

def format_duration(seconds: float) -> str:
    """Format duration seconds to HH:MM:SS.ss"""
    try:
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        return "{:02d}:{:02d}:{:05.2f}".format(int(h), int(m), s)
    except:
        return "00:00:00.00"

def get_ffprobe_info(url: str) -> Optional[Dict[str, Any]]:
    """
    Get media metadata using ffprobe with extended details
    """
    try:
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            url
        ]
        
        # Run process with timeout
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        
        if result.returncode != 0:
            return None
            
        data = json.loads(result.stdout)
        
        format_info = data.get("format", {})
        streams = data.get("streams", [])
        
        # Identify streams
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
        
        # Basic Info
        duration = float(format_info.get("duration", 0))
        size_bytes = int(format_info.get("size", 0))
        overall_bitrate = int(format_info.get("bit_rate", 0)) if format_info.get("bit_rate") != "N/A" else 0
        
        # Determine basic type for high-level "type" field
        media_type = "unknown"
        if video_stream:
             # Check if it's an image (low duration or image codec)
            codec = video_stream.get("codec_name", "")
            if codec in ["png", "mjpeg", "webp", "bmp", "gif", "tiff"] and duration < 1:
                media_type = "image"
            else:
                media_type = "video"
        elif audio_stream:
            media_type = "audio"
            
        # Build Metadata Dictionary
        metadata = {
            # Audio Details
            "audio_bitrate": int(audio_stream.get("bit_rate", 0)) if audio_stream and audio_stream.get("bit_rate") != "N/A" else 0,
            "audio_bitrate_kbps": 0, # Calculated below
            "audio_channels": int(audio_stream.get("channels", 0)) if audio_stream else 0,
            "audio_codec": audio_stream.get("codec_name") if audio_stream else None,
            "audio_codec_long": audio_stream.get("codec_long_name") if audio_stream else None,
            "audio_sample_rate": int(audio_stream.get("sample_rate", 0)) if audio_stream else 0,
            "audio_sample_rate_khz": 0, # Calculated below
            
            # General Details
            "duration": duration,
            "duration_formatted": format_duration(duration),
            "filesize": size_bytes,
            "filesize_mb": round(size_bytes / (1024 * 1024), 2),
            "format": format_info.get("format_name"),
            
            # Flags
            "has_audio": bool(audio_stream),
            "has_video": bool(video_stream) and media_type != "image",
            
            # Bitrate
            "overall_bitrate": overall_bitrate,
            "overall_bitrate_mbps": round(overall_bitrate / 1_000_000, 2)
        }
        
        # Video Specifics (Optional, added for completeness based on video_api)
        if video_stream:
             metadata.update({
                "width": int(video_stream.get("width", 0)),
                "height": int(video_stream.get("height", 0)),
                "video_codec": video_stream.get("codec_name"),
                "video_codec_long": video_stream.get("codec_long_name"),
             })
             
             # FPS Calculation
             fps_str = video_stream.get("r_frame_rate", "0/0")
             if "/" in fps_str:
                num, den = map(int, fps_str.split("/"))
                if den > 0:
                    metadata["fps"] = round(num / den, 2)
        
        # Audio Calculations
        if metadata["audio_bitrate"]:
            metadata["audio_bitrate_kbps"] = int(metadata["audio_bitrate"] / 1000)
            
        if metadata["audio_sample_rate"]:
            metadata["audio_sample_rate_khz"] = int(metadata["audio_sample_rate"] / 1000)
            
        return {
            "type": media_type,
            "metadata": metadata
        }
        
    except Exception as e:
        print(f"FFprobe error: {e}")
        return None
