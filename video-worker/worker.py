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
                camera_smoothing = job_data.get("camera_smoothing", 0.15)
                logger.info(f"Step 2: Converting to portrait with face tracking (sensitivity={sensitivity}, smoothing={camera_smoothing})...")
                clip_path = reframe_to_portrait_with_face_tracking(clip_path, f"{job_id}_portrait", sensitivity, camera_smoothing)
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
        
        # Step 4: Cleanup local files
        logger.info("Step 4: Cleaning up local files...")
        cleanup_files = [
            f"/app/output/{job_id}_original.mp4",
            f"/app/output/{job_id}_portrait.mp4",
            clip_path
        ]
        for f in cleanup_files:
            if os.path.exists(f):
                os.remove(f)
                logger.info(f"Deleted: {f}")
        
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
        
        # Cleanup on error too
        for f in [f"/app/output/{job_id}_original.mp4", f"/app/output/{job_id}_portrait.mp4"]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except:
                    pass


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
        
        # Cleanup local file after upload
        if os.path.exists(caption_result["output_path"]):
            os.remove(caption_result["output_path"])
            logger.info(f"Deleted: {caption_result['output_path']}")
        
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


def process_transcribe_job(job_data):
    """Process YouTube transcription job"""
    job_id = job_data["job_id"]
    logger.info(f"Processing transcribe job: {job_id}")
    
    try:
        redis_client.set(f"job:{job_id}:status", "processing")
        
        youtube_url = job_data["youtube_url"]
        language = job_data.get("language", "id")
        use_whisper = job_data.get("use_whisper", False)  # Default: use YouTube transcript
        model = job_data.get("model", "medium")
        start_time = job_data.get("start_time")
        end_time = job_data.get("end_time")
        
        logger.info(f"YouTube URL: {youtube_url}")
        logger.info(f"Language: {language}, Use Whisper: {use_whisper}")
        
        # Extract video ID from URL
        import re
        video_id_match = re.search(r'(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})', youtube_url)
        if not video_id_match:
            raise Exception("Invalid YouTube URL")
        video_id = video_id_match.group(1)
        
        segments = []
        source = "youtube"
        
        if not use_whisper:
            # Try to get YouTube's built-in transcript (FAST)
            try:
                from youtube_transcript_api import YouTubeTranscriptApi
                
                logger.info("Fetching transcript from YouTube...")
                
                # Try requested language first, then fallback to auto-generated
                try:
                    transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
                    
                    # Try to find manual transcript in requested language
                    try:
                        transcript = transcript_list.find_manually_created_transcript([language])
                    except:
                        # Try auto-generated
                        try:
                            transcript = transcript_list.find_generated_transcript([language])
                        except:
                            # Get any available and translate
                            transcript = transcript_list.find_transcript(['id', 'en', 'auto'])
                            if language not in ['id', 'en']:
                                transcript = transcript.translate(language)
                    
                    transcript_data = transcript.fetch()
                    
                    for item in transcript_data:
                        segment = {
                            "start": round(item['start'], 2),
                            "end": round(item['start'] + item['duration'], 2),
                            "text": item['text']
                        }
                        
                        # Filter by time range if specified
                        if start_time and segment['start'] < start_time:
                            continue
                        if end_time and segment['end'] > end_time:
                            continue
                            
                        segments.append(segment)
                    
                    logger.info(f"Got {len(segments)} segments from YouTube")
                    source = "youtube"
                    
                except Exception as e:
                    logger.warning(f"YouTube transcript not available: {e}")
                    use_whisper = True  # Fallback to Whisper
                    
            except ImportError:
                logger.warning("youtube-transcript-api not installed, using Whisper")
                use_whisper = True
        
        if use_whisper or len(segments) == 0:
            # Use Whisper for transcription (SLOWER but works for any video)
            logger.info("Using Whisper for transcription...")
            source = "whisper"
            
            from modules.fetcher import download_video
            from modules.captioner import extract_audio, transcribe_with_whisper
            
            logger.info("Step 1: Downloading from YouTube...")
            video_path = download_video(youtube_url, job_id, start_time, end_time)
            
            logger.info("Step 2: Extracting audio...")
            audio_path = f"/app/output/{job_id}_audio.wav"
            extract_audio(video_path, audio_path)
            
            logger.info("Step 3: Transcribing with Whisper...")
            transcription = transcribe_with_whisper(audio_path, language, model)
            
            segments = []
            for seg in transcription.get("segments", []):
                segment_data = {
                    "start": round(seg["start"], 2),
                    "end": round(seg["end"], 2),
                    "text": seg["text"].strip()
                }
                if "words" in seg:
                    segment_data["words"] = [
                        {
                            "word": w["word"].strip(),
                            "start": round(w["start"], 2),
                            "end": round(w["end"], 2)
                        }
                        for w in seg["words"]
                    ]
                segments.append(segment_data)
            
            # Cleanup
            import os
            for f in [video_path, audio_path]:
                if os.path.exists(f):
                    os.remove(f)
        
        full_text = " ".join([s["text"] for s in segments])
        
        # Build result
        result = {
            "job_id": job_id,
            "youtube_url": youtube_url,
            "video_id": video_id,
            "language": language,
            "source": source,  # "youtube" or "whisper"
            "transcript": {
                "text": full_text,
                "segments": segments
            }
        }
        
        redis_client.set(f"job:{job_id}:result", json.dumps(result))
        redis_client.set(f"job:{job_id}:status", "completed")
        
        logger.info(f"Transcribe job {job_id} completed: {len(segments)} segments (source: {source})")
        
    except Exception as e:
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        logger.error(f"Error processing transcribe job {job_id}: {error_msg}")
        redis_client.set(f"job:{job_id}:status", "failed")
        redis_client.set(f"job:{job_id}:error", error_msg)


def main():
    logger.info("Video Worker started")
    logger.info(f"Redis URL: {os.getenv('REDIS_URL')}")
    logger.info(f"Storage Endpoint: {os.getenv('STORAGE_ENDPOINT')}")
    logger.info("Listening for video_jobs, caption_jobs, and transcribe_jobs...")
    
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
            
            # Check for transcribe jobs
            transcribe_result = redis_client.brpop("transcribe_jobs", timeout=1)
            if transcribe_result:
                _, job_json = transcribe_result
                job_data = json.loads(job_json)
                process_transcribe_job(job_data)
                continue
            
            # Small sleep if no jobs
            time.sleep(0.5)
                
        except Exception as e:
            logger.error(f"Worker error: {str(e)}")
            time.sleep(5)

if __name__ == "__main__":
    main()