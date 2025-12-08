import redis
import json
import os
import time
import logging
from modules.fetcher import download_video, get_transcript
from modules.topic_engine import find_relevant_segments
from modules.cutter import cut_video_segment
from modules.portrait import reframe_to_portrait
from modules.exporter import upload_to_storage
from modules.callback import send_callback

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))

def process_job(job_data):
    job_id = job_data["job_id"]
    logger.info(f"Processing job: {job_id}")
    
    try:
        redis_client.set(f"job:{job_id}:status", "processing")
        
        logger.info("Step 1: Downloading video...")
        video_path = download_video(job_data["youtube_url"], job_id)
        
        logger.info("Step 2: Getting transcript...")
        transcript = get_transcript(job_data["youtube_url"])
        
        logger.info("Step 3: Finding relevant segments...")
        segments = find_relevant_segments(transcript, job_data["topics"])
        
        clips = []
        
        for idx, segment in enumerate(segments):
            logger.info(f"Processing segment {idx + 1}/{len(segments)}")
            
            clip_path = cut_video_segment(
                video_path, 
                segment["start"], 
                segment["end"],
                f"{job_id}_clip_{idx}"
            )
            
            if job_data["portrait"]:
                clip_path = reframe_to_portrait(clip_path, f"{job_id}_clip_{idx}_portrait")
            
            clip_url = upload_to_storage(clip_path, f"{job_id}_clip_{idx}.mp4")
            
            clips.append({
                "topic": segment.get("topic", "unknown"),
                "url": clip_url,
                "duration": segment["end"] - segment["start"]
            })
        
        result = {
            "job_id": job_id,
            "clips": clips
        }
        
        redis_client.set(f"job:{job_id}:result", json.dumps(result))
        redis_client.set(f"job:{job_id}:status", "completed")
        
        if job_data.get("callback_url"):
            send_callback(job_data["callback_url"], result)
        
        logger.info(f"Job {job_id} completed successfully")
        
    except Exception as e:
        logger.error(f"Error processing job {job_id}: {str(e)}")
        redis_client.set(f"job:{job_id}:status", "failed")
        redis_client.set(f"job:{job_id}:error", str(e))

def main():
    logger.info("Video Worker started")
    
    while True:
        try:
            result = redis_client.brpop("video_jobs", timeout=5)
            
            if result:
                _, job_json = result
                job_data = json.loads(job_json)
                process_job(job_data)
                
        except Exception as e:
            logger.error(f"Worker error: {str(e)}")
            time.sleep(5)

if __name__ == "__main__":
    main()