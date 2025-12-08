import subprocess
import os

def cut_video_segment(input_path: str, start_time: float, end_time: float, output_name: str) -> str:
    """
    Memotong video menggunakan FFmpeg dengan re-encode untuk kualitas baik
    """
    output_path = f"/app/output/{output_name}.mp4"
    
    # Re-encode dengan kualitas tinggi (jangan pakai -c copy)
    cmd = [
        'ffmpeg',
        '-ss', str(start_time),
        '-i', input_path,
        '-t', str(end_time - start_time),
        '-c:v', 'libx264',           # Video codec
        '-preset', 'medium',          # Encoding speed vs quality
        '-crf', '23',                 # Quality (18-28, lower = better)
        '-c:a', 'aac',                # Audio codec
        '-b:a', '128k',               # Audio bitrate
        '-movflags', '+faststart',    # Web optimization
        '-y',
        output_path
    ]
    
    subprocess.run(cmd, check=True, capture_output=True)
    
    return output_path