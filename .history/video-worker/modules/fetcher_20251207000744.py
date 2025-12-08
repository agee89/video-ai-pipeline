import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi
import os

def download_video(youtube_url: str, job_id: str) -> str:
    """
    Download video dari YouTube dengan fallback format options
    """
    output_dir = "/app/output"
    os.makedirs(output_dir, exist_ok=True)
    
    output_path = f"{output_dir}/{job_id}_original.%(ext)s"
    
    ydl_opts = {
        'format': 'best',
        'outtmpl': output_path,
        'quiet': False,
        'no_warnings': False,
        'merge_output_format': 'mp4',
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=True)
            filename = ydl.prepare_filename(info)
            return filename
    except Exception as e:
        raise Exception(f"Failed to download video: {str(e)}")

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