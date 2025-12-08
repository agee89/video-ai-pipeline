import redis
import json
import os
import time
import logging
import traceback

try:
    from modules.fetcher import download_video, get_transcript
    from modules.topic_engine import find_relevant_segments, create_time_based_segments
    from modules.cutter import cut_video_segment
    from modules.portrait import reframe_to_portrait
    from modules.exporter import upload_to_storage
    from modules.callback import send_callback
except ImportError as e:
    logging.error(f"Failed to import modules: {e}")
    raise

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
        logger.info(f"Video downloaded: {video_path}")
        
        logger.info("Step 2: Getting transcript...")
        segments = []
        
        try:
            transcript = get_transcript(job_data["youtube_url"])
            logger.info(f"Transcript retrieved: {len(transcript)} entries")
            
            logger.info("Step 3: Finding relevant segments based on topics...")
            segments = find_relevant_segments(transcript, job_data["topics"])
            logger.info(f"Found {len(segments)} topic-based segments")
            
        except Exception as transcript_error:
            logger.warning(f"Transcript not available: {str(transcript_error)}")
            logger.info("Step 3: Creating time-based segments instead...")
            
            # Fallback: buat segments berdasarkan durasi
            segments = create_time_based_segments(video_path, segment_duration=30)
            logger.info(f"Created {len(segments)} time-based segments")
        
        if not segments:
            raise Exception("Tidak ada segmen yang bisa dibuat dari video ini")
        
        clips = []
        
        for idx, segment in enumerate(segments):
            logger.info(f"Processing segment {idx + 1}/{len(segments)}")
            
            clip_path = cut_video_segment(
                video_path, 
                segment["start"], 
                segment["end"],
                f"{job_id}_clip_{idx}"
            )
            logger.info(f"Clip created: {clip_path}")
            
            if job_data["portrait"]:
                logger.info("Reframing to portrait...")
                clip_path = reframe_to_portrait(clip_path, f"{job_id}_clip_{idx}_portrait")
            
            logger.info("Uploading to storage...")
            clip_url = upload_to_storage(clip_path, f"{job_id}_clip_{idx}.mp4")
            logger.info(f"Uploaded: {clip_url}")
            
            clips.append({
                "topic": segment.get("topic", f"segment_{idx+1}"),
                "url": clip_url,
                "duration": segment["end"] - segment["start"],
                "start": segment["start"],
                "end": segment["end"]
            })
        
        result = {
            "job_id": job_id,
            "clips": clips,
            "has_transcript": len([c for c in clips if c["topic"] not in [f"segment_{i+1}" for i in range(len(clips))]]) > 0
        }
        
        redis_client.set(f"job:{job_id}:result", json.dumps(result))
        redis_client.set(f"job:{job_id}:status", "completed")
        
        if job_data.get("callback_url"):
            send_callback(job_data["callback_url"], result)
        
        logger.info(f"Job {job_id} completed successfully")
        
    except Exception as e:
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        logger.error(f"Error processing job {job_id}: {error_msg}")
        redis_client.set(f"job:{job_id}:status", "failed")
        redis_client.set(f"job:{job_id}:error", error_msg)

def main():
    logger.info("Video Worker started")
    logger.info(f"Redis URL: {os.getenv('REDIS_URL')}")
    logger.info(f"Storage Endpoint: {os.getenv('STORAGE_ENDPOINT')}")
    
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