import subprocess
import os

def cut_video_segment(input_path: str, start_time: float, end_time: float, output_name: str) -> str:
    output_path = f"/app/output/{output_name}.mp4"
    
    cmd = [
        'ffmpeg',
        '-i', input_path,
        '-ss', str(start_time),
        '-to', str(end_time),
        '-c', 'copy',
        '-y',
        output_path
    ]
    
    subprocess.run(cmd, check=True, capture_output=True)
    
    return output_path