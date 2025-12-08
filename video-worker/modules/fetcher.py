import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi
import os
import time
import subprocess
import logging

logger = logging.getLogger("fetcher")

def download_video(youtube_url: str, job_id: str, start_time: float = None, end_time: float = None) -> str:
    """
    Download video dari YouTube.
    Jika start_time/end_time diberikan, coba partial download dulu.
    """
    output_dir = "/app/output"
    os.makedirs(output_dir, exist_ok=True)
    
    output_path = f"{output_dir}/{job_id}_original.mp4"
    
    # If time range specified, try partial download first
    if start_time is not None and end_time is not None:
        logger.info(f"[Fetcher] Trying partial download: {start_time:.1f}s - {end_time:.1f}s")
        
        partial_result = try_partial_download(youtube_url, job_id, start_time, end_time, output_path)
        if partial_result:
            return partial_result
        
        logger.info("[Fetcher] Partial download failed, trying full download...")
    
    # Full download with fallback strategies
    logger.info("[Fetcher] Starting full video download...")
    return full_download(youtube_url, job_id, start_time, end_time, output_path)


def try_partial_download(youtube_url: str, job_id: str, start_time: float, end_time: float, output_path: str) -> str:
    """
    Try to download only the specified segment using yt-dlp CLI.
    Returns output path on success, None on failure.
    """
    output_dir = "/app/output"
    temp_path = f"{output_dir}/{job_id}_partial"
    
    # Use exact time range (no buffer - face tracking handles this)
    section = f"*{start_time:.0f}-{end_time:.0f}"
    
    # Format strategies for CLI
    format_options = [
        "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "22/best",  # 720p
        "18/best",  # 360p
    ]
    
    for fmt in format_options:
        try:
            cmd = [
                'yt-dlp',
                '--format', fmt,
                '--download-sections', section,
                '--force-keyframes-at-cuts',
                '--merge-output-format', 'mp4',
                '--output', f"{temp_path}.%(ext)s",
                '--no-warnings',
                '--retries', '3',
                youtube_url
            ]
            
            logger.info(f"[Fetcher] Partial download: section={section}, format={fmt}")
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                # Find downloaded file
                for ext in ['.mp4', '.webm', '.mkv']:
                    temp_file = f"{temp_path}{ext}"
                    if os.path.exists(temp_file):
                        # Convert to mp4 if needed
                        if temp_file.endswith('.mp4'):
                            os.rename(temp_file, output_path)
                        else:
                            subprocess.run([
                                'ffmpeg', '-i', temp_file,
                                '-c:v', 'libx264', '-crf', '18', '-preset', 'fast',
                                '-c:a', 'aac', '-b:a', '192k',
                                '-y', output_path
                            ], check=True, capture_output=True)
                            os.remove(temp_file)
                        
                        # Verify file size
                        if os.path.exists(output_path) and os.path.getsize(output_path) > 100000:
                            logger.info(f"[Fetcher] Partial download SUCCESS: {output_path}")
                            return output_path
                
        except subprocess.TimeoutExpired:
            logger.warning("[Fetcher] Partial download timeout")
        except Exception as e:
            logger.warning(f"[Fetcher] Partial download error: {e}")
    
    return None


def full_download(youtube_url: str, job_id: str, start_time: float, end_time: float, output_path: str) -> str:
    """
    Full download with post-download segment extraction.
    """
    output_dir = "/app/output"
    temp_path = f"{output_dir}/{job_id}_temp.%(ext)s"
    
    format_strategies = [
        'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        '22/best',
        '18/best',
    ]
    
    base_opts = {
        'outtmpl': temp_path,
        'quiet': False,
        'no_warnings': False,
        'merge_output_format': 'mp4',
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        },
        'retries': 3,
    }
    
    downloaded_file = None
    
    for idx, format_str in enumerate(format_strategies):
        try:
            logger.info(f"[Fetcher] Strategy {idx+1}: {format_str}")
            
            opts = base_opts.copy()
            opts['format'] = format_str
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(youtube_url, download=True)
                downloaded_file = ydl.prepare_filename(info)
                logger.info(f"[Fetcher] Downloaded: {info.get('resolution', 'unknown')}")
                break
                    
        except Exception as e:
            logger.warning(f"[Fetcher] Strategy {idx+1} failed: {e}")
            continue
    
    if not downloaded_file:
        # Try to find any downloaded file
        base = f"{output_dir}/{job_id}_temp"
        for ext in ['.mp4', '.webm', '.mkv']:
            if os.path.exists(base + ext):
                downloaded_file = base + ext
                break
    
    if not downloaded_file or not os.path.exists(downloaded_file):
        raise Exception("All download strategies failed")
    
    # Extract segment if time range specified
    if start_time is not None and end_time is not None:
        # Use exact time range (no buffer)
        duration = end_time - start_time
        
        logger.info(f"[Fetcher] Extracting: {start_time:.1f}s, duration: {duration:.1f}s")
        
        cmd = [
            'ffmpeg',
            '-ss', str(start_time),
            '-i', downloaded_file,
            '-t', str(duration),
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
            '-c:a', 'aac', '-b:a', '192k',
            '-y', output_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise Exception(f"FFmpeg extraction failed: {result.stderr[:200]}")
        
        os.remove(downloaded_file)
    else:
        # No time range, just rename/convert
        if downloaded_file.endswith('.mp4'):
            os.rename(downloaded_file, output_path)
        else:
            subprocess.run([
                'ffmpeg', '-i', downloaded_file,
                '-c:v', 'libx264', '-crf', '18', '-preset', 'fast',
                '-c:a', 'aac', '-b:a', '192k',
                '-y', output_path
            ], check=True, capture_output=True)
            os.remove(downloaded_file)
    
    logger.info(f"[Fetcher] Complete: {output_path}")
    return output_path

def get_transcript(youtube_url: str) -> list:
    """
    Ambil transcript dari video YouTube - ambil bahasa apapun yang tersedia
    """
    video_id = youtube_url.split("v=")[-1].split("&")[0]
    
    try:
        # List semua transcript yang tersedia
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        
        # Coba ambil transcript dalam urutan prioritas
        priority_languages = ['id', 'en', 'en-US', 'en-GB']
        
        # Coba bahasa prioritas dulu
        for lang in priority_languages:
            try:
                transcript = transcript_list.find_transcript([lang])
                return transcript.fetch()
            except:
                continue
        
        # Jika tidak ada bahasa prioritas, ambil transcript pertama yang tersedia
        for transcript in transcript_list:
            try:
                return transcript.fetch()
            except:
                continue
        
        raise Exception("No valid transcript found")
        
    except Exception as e:
        raise Exception(f"Transcript error: {str(e)}")