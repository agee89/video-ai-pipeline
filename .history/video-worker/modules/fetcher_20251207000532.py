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
        # Gunakan format terbaik yang tersedia (fallback ke format apapun)
        'format': 'best',
        'outtmpl': output_path,
        'quiet': False,
        'no_warnings': False,
        # Merge video dan audio jika terpisah
        'merge_output_format': 'mp4',
        # Cookie support untuk video yang butuh auth
        'cookiefile': None,
        # User agent
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=True)
            # Get actual filename
            filename = ydl.prepare_filename(info)
            return filename
    except Exception as e:
        raise Exception(f"Failed to download video: {str(e)}")

def get_transcript(youtube_url: str) -> list:
    """
    Ambil transcript dari video YouTube
    """
    video_id = youtube_url.split("v=")[-1].split("&")[0]
    
    try:
        # Coba berbagai bahasa
        transcript = YouTubeTranscriptApi.get_transcript(
            video_id, 
            languages=['id', 'en', 'en-US', 'en-GB']
        )
        return transcript
    except Exception as e:
        # Coba get transcript list untuk debug
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            available = [t.language_code for t in transcript_list]
            raise Exception(f"Transcript not available in id/en. Available: {available}")
        except:
            raise Exception(f"No transcript available for this video: {str(e)}")