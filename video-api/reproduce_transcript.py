
import sys
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import JSONFormatter
import json

def test_transcript(video_id):
    print(f"Testing video: {video_id}")
    try:
        print("Attempting YouTubeTranscriptApi...")
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        print("Available transcripts:")
        for t in transcript_list:
            print(f" - {t.language_code} ({t.language}) [Generated: {t.is_generated}]")
        
        # Try to fetch manual first, then generated
        try:
             transcript = transcript_list.find_manually_created_transcript(['en', 'id'])
             print("Found manual transcript.")
        except:
             try:
                 transcript = transcript_list.find_generated_transcript(['en', 'id'])
                 print("Found generated transcript.")
             except:
                 print("No suitable transcript found via find_transcript.")
                 return

        data = transcript.fetch()
        print(f"Successfully fetched {len(data)} lines.")
        
    except Exception as e:
        print(f"YouTubeTranscriptApi Error: {e}")
        
    print("\nAttempting yt-dlp fallback...")
    try:
        import yt_dlp
        ydl_opts = {
            'skip_download': True,
            'writeautomaticsub': True,
            'writesubtitles': True,
            'subtitleslangs': ['en', 'id'],
            'quiet': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            if 'subtitles' in info and info['subtitles']:
                print(f"yt-dlp found manual subtitles: {list(info['subtitles'].keys())}")
            if 'automatic_captions' in info and info['automatic_captions']:
                print(f"yt-dlp found auto captions: {list(info['automatic_captions'].keys())}")
            else:
                print("yt-dlp found NO subtitles.")
                
    except Exception as e:
        print(f"yt-dlp Error: {e}")

if __name__ == "__main__":
    url = "https://www.youtube.com/watch?v=BnxHEqmCxpE"
    if "v=" in url:
        video_id = url.split("v=")[1].split("&")[0]
    else:
        video_id = url
    test_transcript(video_id)
