import redis
import json
import os
import time
import logging
import traceback
import sys

try:
    from modules.fetcher import download_video
    from modules.portrait import reframe_to_portrait, reframe_to_portrait_with_face_tracking
    from modules.exporter import upload_to_storage
    from modules.callback import send_callback
    from modules.captioner import add_captions_to_video
    from modules.thumbnail import generate_thumbnail
    from modules.video_source import add_video_source_to_video
    from modules.image_watermark import add_image_watermark_to_video
    from modules.video_merge import merge_videos
    from modules.image_to_video import create_video_from_images
except ImportError as e:
    logging.error(f"Failed to import modules: {e}")
    raise


# ==================== IMPROVED LOGGING ====================

class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors and better formatting"""
    
    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[35m',  # Magenta
    }
    RESET = '\033[0m'
    BOLD = '\033[1m'
    
    def format(self, record):
        # Add color based on level
        color = self.COLORS.get(record.levelname, self.RESET)
        
        # Format timestamp
        timestamp = self.formatTime(record, '%Y-%m-%d %H:%M:%S')
        
        # Format the message
        level = f"{color}{record.levelname:8}{self.RESET}"
        module = f"\033[34m{record.name:20}\033[0m"
        message = record.getMessage()
        
        # Add job_id if present in extra
        job_id = getattr(record, 'job_id', None)
        if job_id:
            return f"{timestamp} | {level} | {self.BOLD}[{job_id}]{self.RESET} | {message}"
        else:
            return f"{timestamp} | {level} | {module} | {message}"


def setup_logging():
    """Setup improved logging configuration"""
    # Create handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    
    # Set formatter
    formatter = ColoredFormatter()
    handler.setFormatter(formatter)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers = []  # Remove default handlers
    root_logger.addHandler(handler)
    
    # Reduce noise from other libraries
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('matplotlib').setLevel(logging.WARNING)
    logging.getLogger('PIL').setLevel(logging.WARNING)


setup_logging()
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
            "clip_number": job_data.get("clip_number"),
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
            "caps_number": job_data.get("caps_number"),
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


def process_thumbnail_job(job_data):
    """Process thumbnail generation job"""
    job_id = job_data["job_id"]
    logger.info(f"Processing thumbnail job: {job_id}")
    
    try:
        redis_client.set(f"job:{job_id}:status", "processing")
        
        video_url = job_data.get("video_url")
        background_image = job_data.get("background_image")
        size = job_data.get("size", "1080x1920")
        frame_selection = job_data.get("frame_selection")
        text_overlay = job_data.get("text_overlay")
        export_settings = job_data.get("export", {"format": "png"})
        
        video_path = None
        
        # Download video if needed
        if video_url and not background_image:
            # Convert external URL to internal Docker URL
            internal_url = video_url.replace("minio-video", "minio")
            logger.info(f"Downloading video: {internal_url}")
            import requests
            video_path = f"/app/output/{job_id}_source.mp4"
            
            response = requests.get(internal_url, stream=True, timeout=60)
            response.raise_for_status()
            with open(video_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info(f"Video downloaded: {video_path}")
        
        # Generate thumbnail
        output_format = export_settings.get("format", "png")
        output_path = f"/app/output/{job_id}_thumbnail.{output_format}"
        
        thumbnail_path = generate_thumbnail(
            video_path=video_path,
            output_path=output_path,
            size=size,
            frame_selection=frame_selection,
            background_image=background_image,
            text_overlay=text_overlay,
            export_settings=export_settings
        )
        
        logger.info(f"Thumbnail generated: {thumbnail_path}")
        
        # Upload to storage
        filename = f"{job_id}.{output_format}"
        upload_result = upload_to_storage(thumbnail_path, filename)
        logger.info(f"Uploaded: {upload_result['url']}")
        
        # Cleanup
        if video_path and os.path.exists(video_path):
            os.remove(video_path)
        if os.path.exists(thumbnail_path):
            os.remove(thumbnail_path)
        
        # Build result
        result = {
            "job_id": job_id,
            "thumbnail_number": job_data.get("thumbnail_number"),
            "thumbnail": {
                "url": upload_result["url"],
                "url_external": upload_result["url_external"],
                "size": size,
                "format": output_format
            }
        }
        
        redis_client.set(f"job:{job_id}:result", json.dumps(result))
        redis_client.set(f"job:{job_id}:status", "completed")
        
        if job_data.get("callback_url"):
            send_callback(job_data["callback_url"], result)
        
        logger.info(f"Thumbnail job {job_id} completed")
        
    except Exception as e:
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        logger.error(f"Error processing thumbnail job {job_id}: {error_msg}")
        redis_client.set(f"job:{job_id}:status", "failed")
        redis_client.set(f"job:{job_id}:error", error_msg)


def process_video_source_job(job_data):
    """Process video source overlay job"""
    job_id = job_data["job_id"]
    logger.info(f"Processing video source job: {job_id}")
    
    try:
        redis_client.set(f"job:{job_id}:status", "processing")
        
        video_url = job_data["video_url"]
        channel_name = job_data["channel_name"]
        prefix = job_data.get("prefix", "FullVideo:")
        text_style = job_data.get("text_style", {})
        background = job_data.get("background", {})
        position = job_data.get("position", {})
        
        logger.info(f"Video URL: {video_url}")
        logger.info(f"Channel: {prefix} {channel_name}")
        
        # Process video source overlay
        result_data = add_video_source_to_video(
            video_url=video_url,
            job_id=job_id,
            channel_name=channel_name,
            prefix=prefix,
            text_style=text_style,
            background=background,
            position=position
        )
        
        # Upload to storage
        logger.info("Uploading video with source overlay...")
        upload_result = upload_to_storage(result_data["output_path"], f"{job_id}.mp4")
        logger.info(f"Uploaded - n8n: {upload_result['url']}, External: {upload_result['url_external']}")
        
        # Cleanup local file
        if os.path.exists(result_data["output_path"]):
            os.remove(result_data["output_path"])
            logger.info(f"Deleted: {result_data['output_path']}")
        
        # Build result
        result = {
            "job_id": job_id,
            "video": {
                "url": upload_result['url'],
                "url_external": upload_result['url_external']
            },
            "display_text": result_data.get("display_text", "")
        }
        
        redis_client.set(f"job:{job_id}:result", json.dumps(result))
        redis_client.set(f"job:{job_id}:status", "completed")
        
        if job_data.get("callback_url"):
            send_callback(job_data["callback_url"], result)
        
        logger.info(f"Video source job {job_id} completed successfully")
        
    except Exception as e:
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        logger.error(f"Error processing video source job {job_id}: {error_msg}")
        redis_client.set(f"job:{job_id}:status", "failed")
        redis_client.set(f"job:{job_id}:error", error_msg)


def process_image_watermark_job(job_data):
    """Process image watermark job"""
    job_id = job_data["job_id"]
    logger.info(f"Processing image watermark job: {job_id}")
    
    try:
        redis_client.set(f"job:{job_id}:status", "processing")
        
        video_url = job_data["video_url"]
        image_url = job_data["image_url"]
        size = job_data.get("size", {})
        position = job_data.get("position", {})
        opacity = job_data.get("opacity", 1.0)
        
        logger.info(f"Video URL: {video_url}")
        logger.info(f"Image URL: {image_url}")
        logger.info(f"Position: {position.get('position', 'bottom_right')}, Opacity: {opacity}")
        
        # Process image watermark
        result_data = add_image_watermark_to_video(
            video_url=video_url,
            image_url=image_url,
            job_id=job_id,
            size=size,
            position=position,
            opacity=opacity
        )
        
        # Upload to storage
        logger.info("Uploading video with image watermark...")
        upload_result = upload_to_storage(result_data["output_path"], f"{job_id}.mp4")
        logger.info(f"Uploaded - n8n: {upload_result['url']}, External: {upload_result['url_external']}")
        
        # Cleanup local file
        if os.path.exists(result_data["output_path"]):
            os.remove(result_data["output_path"])
            logger.info(f"Deleted: {result_data['output_path']}")
        
        # Build result
        result = {
            "job_id": job_id,
            "video": {
                "url": upload_result['url'],
                "url_external": upload_result['url_external']
            },
            "watermark": {
                "position": result_data.get("position"),
                "opacity": result_data.get("opacity")
            }
        }
        
        redis_client.set(f"job:{job_id}:result", json.dumps(result))
        redis_client.set(f"job:{job_id}:status", "completed")
        
        if job_data.get("callback_url"):
            send_callback(job_data["callback_url"], result)
        
        logger.info(f"Image watermark job {job_id} completed successfully")
        
    except Exception as e:
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        logger.error(f"Error processing image watermark job {job_id}: {error_msg}")
        redis_client.set(f"job:{job_id}:status", "failed")
        redis_client.set(f"job:{job_id}:error", error_msg)


def process_merge_videos_job(job_data):
    """Process video merge job"""
    job_id = job_data["job_id"]
    logger.info(f"Processing merge videos job: {job_id}")
    
    try:
        redis_client.set(f"job:{job_id}:status", "processing")
        
        video_urls = job_data["videos"]
        
        logger.info(f"Merging {len(video_urls)} videos")
        for i, url in enumerate(video_urls):
            logger.info(f"  Video {i+1}: {url}")
        
        # Process merge
        result_data = merge_videos(
            video_urls=video_urls,
            job_id=job_id
        )
        
        # Upload merged video
        logger.info("Uploading merged video...")
        upload_result = upload_to_storage(result_data["output_path"], f"{job_id}.mp4")
        logger.info(f"Uploaded - n8n: {upload_result['url']}, External: {upload_result['url_external']}")
        
        # Cleanup local file
        if os.path.exists(result_data["output_path"]):
            os.remove(result_data["output_path"])
            logger.info(f"Deleted: {result_data['output_path']}")
        
        # Build result
        result = {
            "job_id": job_id,
            "video": {
                "url": upload_result['url'],
                "url_external": upload_result['url_external']
            },
            "merged": {
                "video_count": result_data.get("video_count")
            }
        }
        
        redis_client.set(f"job:{job_id}:result", json.dumps(result))
        redis_client.set(f"job:{job_id}:status", "completed")
        
        if job_data.get("callback_url"):
            send_callback(job_data["callback_url"], result)
        
        logger.info(f"Merge videos job {job_id} completed successfully")
        
    except Exception as e:
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        logger.error(f"Error processing merge videos job {job_id}: {error_msg}")
        redis_client.set(f"job:{job_id}:status", "failed")
        redis_client.set(f"job:{job_id}:error", error_msg)


def process_image_to_video_job(job_data):
    """Process image to video job"""
    job_id = job_data["job_id"]
    logger.info(f"Processing image to video job: {job_id}")
    
    try:
        redis_client.set(f"job:{job_id}:status", "processing")
        
        images = job_data["images"]
        fps = job_data.get("fps", 30)
        transition = job_data.get("transition")
        motion = job_data.get("motion")
        motion_intensity = job_data.get("motion_intensity", 0.3)
        
        logger.info(f"Creating video from {len(images)} image(s)")
        logger.info(f"FPS: {fps}, Transition: {transition or 'none'}, Motion: {motion or 'none'} (intensity: {motion_intensity})")
        
        # Process image to video
        result_data = create_video_from_images(
            images=images,
            job_id=job_id,
            fps=fps,
            transition=transition,
            motion=motion,
            motion_intensity=motion_intensity
        )
        
        # Upload video
        logger.info("Uploading video...")
        upload_result = upload_to_storage(result_data["output_path"], f"{job_id}.mp4")
        logger.info(f"Uploaded - n8n: {upload_result['url']}, External: {upload_result['url_external']}")
        
        # Cleanup local file
        if os.path.exists(result_data["output_path"]):
            os.remove(result_data["output_path"])
            logger.info(f"Deleted: {result_data['output_path']}")
        
        # Build result
        result = {
            "job_id": job_id,
            "video": {
                "url": upload_result['url'],
                "url_external": upload_result['url_external']
            },
            "details": {
                "image_count": result_data.get("image_count"),
                "transition": result_data.get("transition")
            }
        }
        
        redis_client.set(f"job:{job_id}:result", json.dumps(result))
        redis_client.set(f"job:{job_id}:status", "completed")
        
        if job_data.get("callback_url"):
            send_callback(job_data["callback_url"], result)
        
        logger.info(f"Image to video job {job_id} completed successfully")
        
    except Exception as e:
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        logger.error(f"Error processing image to video job {job_id}: {error_msg}")
        redis_client.set(f"job:{job_id}:status", "failed")
        redis_client.set(f"job:{job_id}:error", error_msg)


def main():
    logger.info("Video Worker started")
    logger.info(f"Redis URL: {os.getenv('REDIS_URL')}")
    logger.info(f"Storage Endpoint: {os.getenv('STORAGE_ENDPOINT')}")
    logger.info("Listening for video_jobs, caption_jobs, transcribe_jobs, thumbnail_jobs, video_source_jobs, image_watermark_jobs, merge_videos_jobs, and image_to_video_jobs...")
    
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
            
            # Check for thumbnail jobs
            thumbnail_result = redis_client.brpop("thumbnail_jobs", timeout=1)
            if thumbnail_result:
                _, job_json = thumbnail_result
                job_data = json.loads(job_json)
                process_thumbnail_job(job_data)
                continue
            
            # Check for video source jobs
            video_source_result = redis_client.brpop("video_source_jobs", timeout=1)
            if video_source_result:
                _, job_json = video_source_result
                job_data = json.loads(job_json)
                process_video_source_job(job_data)
                continue
            
            # Check for image watermark jobs
            image_watermark_result = redis_client.brpop("image_watermark_jobs", timeout=1)
            if image_watermark_result:
                _, job_json = image_watermark_result
                job_data = json.loads(job_json)
                process_image_watermark_job(job_data)
                continue
            
            # Check for merge videos jobs
            merge_videos_result = redis_client.brpop("merge_videos_jobs", timeout=1)
            if merge_videos_result:
                _, job_json = merge_videos_result
                job_data = json.loads(job_json)
                process_merge_videos_job(job_data)
                continue
            
            # Check for image to video jobs
            image_to_video_result = redis_client.brpop("image_to_video_jobs", timeout=1)
            if image_to_video_result:
                _, job_json = image_to_video_result
                job_data = json.loads(job_json)
                process_image_to_video_job(job_data)
                continue
            
            # Small sleep if no jobs
            time.sleep(0.5)
                
        except Exception as e:
            logger.error(f"Worker error: {str(e)}")
            time.sleep(5)

if __name__ == "__main__":
    main()