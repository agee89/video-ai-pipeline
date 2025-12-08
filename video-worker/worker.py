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
    from modules.captioner import add_captions_to_video
except ImportError as e:
    logging.error(f"Failed to import modules: {e}")
    raise

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))


def process_video_job(job_data):
    """Process video clipping job"""
    job_id = job_data["job_id"]
    logger.info(f"Processing video job: {job_id}")
    
    try:
        redis_client.set(f"job:{job_id}:status", "processing")
        
        start_time = job_data["start_time"]
        end_time = job_data["end_time"]
        duration = end_time - start_time
        
        logger.info(f"Clip range: {start_time:.2f}s - {end_time:.2f}s (duration: {duration:.2f}s)")
        
        # Step 1: Download
        logger.info("Step 1: Downloading video segment...")
        clip_path = download_video(
            job_data["youtube_url"], 
            job_id,
            start_time,
            end_time
        )
        logger.info(f"Video segment downloaded: {clip_path}")
        
        # Step 2: Portrait conversion (optional)
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
                "url": upload_result['url'],
                "url_external": upload_result['url_external'],
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
        
        logger.info(f"Video job {job_id} completed successfully")
        
    except Exception as e:
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        logger.error(f"Error processing video job {job_id}: {error_msg}")
        redis_client.set(f"job:{job_id}:status", "failed")
        redis_client.set(f"job:{job_id}:error", error_msg)


def process_caption_job(job_data):
    """Process caption/subtitle job"""
    job_id = job_data["job_id"]
    logger.info(f"Processing caption job: {job_id}")
    
    try:
        redis_client.set(f"job:{job_id}:status", "processing")
        
        video_url = job_data["video_url"]
        language = job_data.get("language", "id")
        model = job_data.get("model", "medium")
        settings = job_data.get("settings", {})
        
        logger.info(f"Video URL: {video_url}")
        logger.info(f"Language: {language}, Model: {model}")
        
        # Process captions
        caption_result = add_captions_to_video(
            video_url=video_url,
            job_id=job_id,
            language=language,
            model=model,
            settings=settings
        )
        
        # Upload captioned video
        logger.info("Uploading captioned video...")
        upload_result = upload_to_storage(caption_result["output_path"], f"{job_id}.mp4")
        logger.info(f"Uploaded - n8n: {upload_result['url']}, External: {upload_result['url_external']}")
        
        # Build result
        result = {
            "job_id": job_id,
            "video": {
                "url": upload_result['url'],
                "url_external": upload_result['url_external']
            },
            "transcript": caption_result.get("transcript", "")
        }
        
        redis_client.set(f"job:{job_id}:result", json.dumps(result))
        redis_client.set(f"job:{job_id}:status", "completed")
        
        if job_data.get("callback_url"):
            send_callback(job_data["callback_url"], result)
        
        logger.info(f"Caption job {job_id} completed successfully")
        
    except Exception as e:
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        logger.error(f"Error processing caption job {job_id}: {error_msg}")
        redis_client.set(f"job:{job_id}:status", "failed")
        redis_client.set(f"job:{job_id}:error", error_msg)


def main():
    logger.info("Video Worker started")
    logger.info(f"Redis URL: {os.getenv('REDIS_URL')}")
    logger.info(f"Storage Endpoint: {os.getenv('STORAGE_ENDPOINT')}")
    logger.info("Listening for video_jobs and caption_jobs...")
    
    while True:
        try:
            # Check for video jobs
            video_result = redis_client.brpop("video_jobs", timeout=1)
            if video_result:
                _, job_json = video_result
                job_data = json.loads(job_json)
                process_video_job(job_data)
                continue
            
            # Check for caption jobs
            caption_result = redis_client.brpop("caption_jobs", timeout=1)
            if caption_result:
                _, job_json = caption_result
                job_data = json.loads(job_json)
                process_caption_job(job_data)
                continue
            
            # Small sleep if no jobs
            time.sleep(0.5)
                
        except Exception as e:
            logger.error(f"Worker error: {str(e)}")
            time.sleep(5)

if __name__ == "__main__":
    main()