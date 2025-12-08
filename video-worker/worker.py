import redis
import json
import os
import time
import logging
import traceback

try:
    from modules.fetcher import download_video
    from modules.portrait import reframe_to_portrait, reframe_to_portrait_with_face_tracking
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
        
        start_time = job_data["start_time"]
        end_time = job_data["end_time"]
        duration = end_time - start_time
        
        logger.info(f"Clip range: {start_time:.2f}s - {end_time:.2f}s (duration: {duration:.2f}s)")
        
        # Step 1: Download hanya bagian yang dibutuhkan
        logger.info("Step 1: Downloading video segment...")
        logger.info(f"Time range: {start_time:.2f}s - {end_time:.2f}s (duration: {duration:.2f}s)")
        
        clip_path = download_video(
            job_data["youtube_url"], 
            job_id,
            start_time,
            end_time
        )
        logger.info(f"Video segment downloaded: {clip_path}")
        
        # Step 2: Portrait conversion (opsional)
        if job_data.get("portrait", False):
            if job_data.get("face_tracking", False):
                sensitivity = job_data.get("tracking_sensitivity", 5)
                logger.info(f"Step 2: Converting to portrait with face tracking (sensitivity={sensitivity})...")
                clip_path = reframe_to_portrait_with_face_tracking(clip_path, f"{job_id}_portrait", sensitivity)
            else:
                logger.info("Step 2: Converting to portrait (center crop)...")
                clip_path = reframe_to_portrait(clip_path, f"{job_id}_portrait")
            logger.info(f"Portrait conversion complete: {clip_path}")
        else:
            logger.info("Step 2: Skipping portrait conversion (not requested)")
        
        # Step 3: Upload to storage
        logger.info("Step 3: Uploading to storage...")
        upload_result = upload_to_storage(clip_path, f"{job_id}.mp4")
        logger.info(f"Uploaded - n8n: {upload_result['url']}, External: {upload_result['url_external']}")
        
        # Build result
        result = {
            "job_id": job_id,
            "clip": {
                "url": upload_result['url'],                   # For n8n/Docker access (minio-video:9002)
                "url_external": upload_result['url_external'], # For browser access (localhost:9002)
                "start_time": start_time,
                "end_time": end_time,
                "duration": duration,
                "portrait": job_data.get("portrait", False),
                "face_tracking": job_data.get("face_tracking", False)
            }
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