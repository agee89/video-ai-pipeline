import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi
import os

def download_video(youtube_url: str, job_id: str) -> str:
    output_dir = "/app/output"
    os.makedirs(output_dir, exist_ok=True)
    
    output_path = f"{output_dir}/{job_id}_original.mp4"
    
    ydl_opts = {
        'format': 'best[ext=mp4]',
        'outtmpl': output_path,
        'quiet': True
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([youtube_url])
    
    return output_path

def get_transcript(youtube_url: str) -> list:
    video_id = youtube_url.split("v=")[-1].split("&")[0]
    
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['id', 'en'])
        return transcript
    except Exception as e:
        raise Exception(f"Transcript not available: {str(e)}")