import subprocess
import os

def cut_video_segment(input_path: str, start_time: float, end_time: float, output_name: str) -> str:
    """
    Memotong video menggunakan FFmpeg dengan re-encode untuk potongan yang presisi.
    Stream copy hanya bisa memotong di keyframe, menyebabkan offset 1-5 detik.
    Re-encode memungkinkan pemotongan frame-accurate.
    """
    output_path = f"/app/output/{output_name}.mp4"
    duration = end_time - start_time
    
    print(f"[Cutter] Cutting {start_time:.2f}s to {end_time:.2f}s (duration: {duration:.2f}s)")
    
    # Gunakan re-encode untuk potongan yang presisi
    # -ss sebelum -i = fast seek ke posisi terdekat
    # -ss setelah -i = precise seek (tapi lambat)
    # Kombinasi keduanya: seek cepat dulu, lalu precise
    cmd = [
        'ffmpeg',
        '-ss', str(start_time),         # Fast seek (sebelum -i)
        '-i', input_path,
        '-t', str(duration),            # Duration, bukan end time
        '-c:v', 'libx264',              # Re-encode video
        '-preset', 'slow',              # Better quality
        '-crf', '18',                   # High quality (visually lossless)
        '-c:a', 'aac',                  # Re-encode audio
        '-b:a', '192k',                 # High quality audio
        '-movflags', '+faststart',      # Web optimization
        '-avoid_negative_ts', 'make_zero',
        '-y',
        output_path
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"[Cutter] FFmpeg error: {result.stderr}")
        raise Exception(f"FFmpeg failed: {result.stderr}")
    
    # Verify output duration
    probe_cmd = [
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        output_path
    ]
    probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
    actual_duration = float(probe_result.stdout.strip()) if probe_result.stdout.strip() else 0
    
    print(f"[Cutter] Output duration: {actual_duration:.2f}s (expected: {duration:.2f}s)")
    
    return output_path