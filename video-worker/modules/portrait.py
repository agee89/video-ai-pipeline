import subprocess
import os
import json
import logging
import sys

# Ensure logs are flushed immediately
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("portrait")

def reframe_to_portrait(input_path: str, output_name: str) -> str:
    """
    Reframe video ke portrait 9:16 dengan kualitas tinggi (center crop)
    """
    output_path = f"/app/output/{output_name}.mp4"
    
    try:
        probe_cmd = [
            'ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height', '-of', 'json', input_path
        ]
        
        result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
        info = json.loads(result.stdout)
        
        original_width = int(info['streams'][0]['width'])
        original_height = int(info['streams'][0]['height'])
        
        logger.info(f"[Portrait] Original: {original_width}x{original_height}")
        
        target_height = original_height
        target_width = int(target_height * 9 / 16)
        
        if original_width < target_width:
            target_width = original_width
            target_height = int(target_width * 16 / 9)
        
        crop_x = (original_width - target_width) // 2
        
        cmd = [
            'ffmpeg', '-i', input_path,
            '-vf', f'crop={target_width}:{target_height}:{crop_x}:0,scale=1080:1920:flags=lanczos',
            '-c:v', 'libx264', '-preset', 'slow', '-crf', '18',
            '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart',
            '-y', output_path
        ]
        
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.info(f"[Portrait] Complete: {output_path}")
        return output_path
        
    except Exception as e:
        logger.error(f"[Portrait] Error: {str(e)}")
        raise Exception(f"Portrait reframe failed: {str(e)}")


def reframe_to_portrait_with_face_tracking(input_path: str, output_name: str, sensitivity: int = 5) -> str:
    """
    Portrait dengan face tracking menggunakan HYBRID approach:
    1. Face Detection (untuk wide shot, bekerja dari jarak jauh)
    2. Face Mesh (untuk close-up, deteksi bibir)
    
    Selalu fokus pada salah satu orang, prioritas yang lebih aktif.
    """
    import traceback
    
    output_path = f"/app/output/{output_name}_temp.mp4"
    final_output = f"/app/output/{output_name}.mp4"
    
    # Smoothing: sensitivity 1-10 -> 0.02 - 0.10
    smoothing_factor = 0.02 + (sensitivity - 1) * 0.009
    
    logger.info(f"[FaceTrack] Starting (sensitivity={sensitivity}, smoothing={smoothing_factor:.3f})")
    
    try:
        import cv2
        import mediapipe as mp
        import numpy as np
    except ImportError as e:
        logger.error(f"[FaceTrack] Import error: {e}")
        return reframe_to_portrait(input_path, output_name)
    
    try:
        # Initialize BOTH detectors
        # 1. Face Detection - works better for distant/small faces
        mp_face_detection = mp.solutions.face_detection
        face_detector = mp_face_detection.FaceDetection(
            model_selection=1,  # 1 = full range (better for distant faces)
            min_detection_confidence=0.3
        )
        
        # 2. Face Mesh - for lip tracking on close-up faces
        mp_face_mesh = mp.solutions.face_mesh
        face_mesh = mp_face_mesh.FaceMesh(
            max_num_faces=4,
            min_detection_confidence=0.3,
            min_tracking_confidence=0.3
        )
        
        logger.info("[FaceTrack] Face Detection + Face Mesh initialized (hybrid mode)")
        
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            raise Exception(f"Cannot open video: {input_path}")
        
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        logger.info(f"[FaceTrack] Video: {width}x{height}, {fps:.1f}fps, {total_frames} frames")
        
        # Target 9:16 portrait
        target_width = int(height * 9 / 16)
        if target_width > width:
            target_width = width
            target_height = int(target_width * 16 / 9)
        else:
            target_height = height
        
        logger.info(f"[FaceTrack] Crop size: {target_width}x{target_height}")
        
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, fps, (target_width, target_height))
        
        if not out.isOpened():
            raise Exception("Failed to create VideoWriter")
        
        # Lip landmarks
        UPPER_LIP = 13
        LOWER_LIP = 14
        
        # === TRACKING STATE ===
        # Current tracked face position (smoothed)
        tracked_face_x = None
        smooth_crop_x = None
        
        # Activity scores per face (by approximate X position bucket)
        NUM_BUCKETS = 8
        BUCKET_WIDTH = width // NUM_BUCKETS
        face_activity = {}  # bucket -> activity score
        face_last_seen = {}  # bucket -> last frame detected
        
        # Detection settings
        detect_interval = max(1, int(fps / 8))  # 8 times per second
        
        frame_count = 0
        max_frames = int(fps * 300)
        detection_count = 0
        mesh_count = 0
        
        logger.info(f"[FaceTrack] Processing (detect every {detect_interval} frames)...")
        
        while cap.isOpened() and frame_count < max_frames:
            ret, frame = cap.read()
            if not ret:
                break
            
            # === FACE DETECTION (every N frames) ===
            if frame_count % detect_interval == 0:
                try:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    
                    faces_this_frame = []
                    
                    # STEP 1: Use Face Detection first (works better at distance)
                    detection_results = face_detector.process(rgb)
                    
                    if detection_results.detections:
                        detection_count += 1
                        
                        for detection in detection_results.detections:
                            bbox = detection.location_data.relative_bounding_box
                            face_x = int((bbox.xmin + bbox.width / 2) * width)
                            face_size = bbox.width * bbox.height * width * height
                            
                            # Calculate bucket for this face
                            bucket = min(face_x // BUCKET_WIDTH, NUM_BUCKETS - 1)
                            
                            # Update last seen
                            face_last_seen[bucket] = frame_count
                            
                            # Initialize activity if new face
                            if bucket not in face_activity:
                                face_activity[bucket] = 0
                            
                            faces_this_frame.append({
                                'x': face_x,
                                'size': face_size,
                                'bucket': bucket,
                                'lip_activity': 0
                            })
                    
                    # STEP 2: Try Face Mesh for lip tracking (works for close-up)
                    mesh_results = face_mesh.process(rgb)
                    
                    if mesh_results.multi_face_landmarks:
                        mesh_count += 1
                        
                        for face_landmarks in mesh_results.multi_face_landmarks:
                            nose = face_landmarks.landmark[1]
                            mesh_face_x = int(nose.x * width)
                            
                            # Lip opening
                            upper = face_landmarks.landmark[UPPER_LIP]
                            lower = face_landmarks.landmark[LOWER_LIP]
                            lip_open = abs(lower.y - upper.y) * height
                            
                            # Find matching face from detection
                            mesh_bucket = min(mesh_face_x // BUCKET_WIDTH, NUM_BUCKETS - 1)
                            
                            # Update activity based on lip opening
                            if mesh_bucket in face_activity:
                                # Activity increases with lip opening (proxy for speaking)
                                face_activity[mesh_bucket] = 0.8 * face_activity[mesh_bucket] + 0.2 * lip_open
                            
                            # Update faces_this_frame with lip data
                            for f in faces_this_frame:
                                if abs(f['x'] - mesh_face_x) < BUCKET_WIDTH:
                                    f['lip_activity'] = lip_open
                                    break
                    
                    # STEP 3: Determine which face to track
                    if faces_this_frame:
                        # Decay activity for faces not seen recently
                        current_time = frame_count
                        for b in list(face_activity.keys()):
                            if b not in face_last_seen or current_time - face_last_seen[b] > fps * 2:
                                face_activity[b] *= 0.9  # Decay
                        
                        # Pick face with highest activity, or largest if no activity
                        best_face = None
                        best_score = -1
                        
                        for f in faces_this_frame:
                            bucket = f['bucket']
                            activity = face_activity.get(bucket, 0)
                            # Score = activity (speaking) + size bonus
                            score = activity + f['size'] / 100000
                            
                            if score > best_score:
                                best_score = score
                                best_face = f
                        
                        if best_face:
                            # Update tracked face with smoothing
                            if tracked_face_x is None:
                                tracked_face_x = float(best_face['x'])
                                logger.info(f"[FaceTrack] Initial lock: x={best_face['x']}")
                            else:
                                # Check if should switch to another face (much higher activity)
                                current_bucket = min(int(tracked_face_x) // BUCKET_WIDTH, NUM_BUCKETS - 1)
                                current_activity = face_activity.get(current_bucket, 0)
                                best_activity = face_activity.get(best_face['bucket'], 0)
                                
                                # Switch if: different face AND 2x more active AND has recent activity
                                if (best_face['bucket'] != current_bucket and 
                                    best_activity > current_activity * 2 and 
                                    best_activity > 1.0):
                                    logger.info(f"[FaceTrack] Switch: {int(tracked_face_x)} -> {best_face['x']} (activity {current_activity:.1f} -> {best_activity:.1f})")
                                    tracked_face_x = float(best_face['x'])
                                else:
                                    # Update position smoothly (follow same person)
                                    for f in faces_this_frame:
                                        if f['bucket'] == current_bucket or abs(f['x'] - tracked_face_x) < width // 4:
                                            tracked_face_x = 0.85 * tracked_face_x + 0.15 * f['x']
                                            break
                    
                    else:
                        # No faces detected this frame - keep tracking last position
                        # This prevents jumping to center when detection fails
                        pass
                
                except Exception as e:
                    logger.warning(f"[FaceTrack] Detection error at frame {frame_count}: {e}")
            
            # === CALCULATE CROP POSITION ===
            if tracked_face_x is not None:
                target_crop_x = tracked_face_x - target_width // 2
            else:
                # No face ever detected - use center (fallback)
                target_crop_x = (width - target_width) // 2
            
            target_crop_x = max(0, min(target_crop_x, width - target_width))
            
            # Initialize smooth crop
            if smooth_crop_x is None:
                smooth_crop_x = float(target_crop_x)
            
            # Smooth camera movement
            smooth_crop_x += smoothing_factor * (target_crop_x - smooth_crop_x)
            crop_x = int(smooth_crop_x)
            crop_x = max(0, min(crop_x, width - target_width))
            
            crop_y = max(0, (height - target_height) // 2)
            
            # Crop and write frame
            cropped = frame[crop_y:crop_y+target_height, crop_x:crop_x+target_width]
            
            if cropped.shape[0] != target_height or cropped.shape[1] != target_width:
                cropped = cv2.resize(cropped, (target_width, target_height))
            
            out.write(cropped)
            frame_count += 1
            
            if frame_count % 300 == 0:
                face_str = f"{tracked_face_x:.0f}" if tracked_face_x else "none"
                logger.info(f"[FaceTrack] Frame {frame_count}/{total_frames}, tracked_x={face_str}, crop_x={crop_x}")
        
        cap.release()
        out.release()
        face_detector.close()
        face_mesh.close()
        
        detection_rate = (detection_count / (frame_count // detect_interval)) * 100 if frame_count > 0 else 0
        logger.info(f"[FaceTrack] Done: {frame_count} frames, detection rate={detection_rate:.1f}%, mesh={mesh_count}")
        
        if frame_count == 0:
            raise Exception("No frames processed")
        
        # Re-encode with audio
        logger.info("[FaceTrack] Re-encoding with audio...")
        
        cmd = [
            'ffmpeg', '-loglevel', 'error',
            '-i', output_path, '-i', input_path,
            '-map', '0:v:0', '-map', '1:a:0?',
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
            '-vf', 'scale=1080:-2',
            '-c:a', 'aac', '-b:a', '192k',
            '-movflags', '+faststart', '-shortest',
            '-y', final_output
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise Exception(f"FFmpeg failed: {result.stderr[-200:] if result.stderr else 'unknown'}")
        
        if os.path.exists(output_path):
            os.remove(output_path)
        
        logger.info(f"[FaceTrack] Complete: {final_output}")
        return final_output
        
    except Exception as e:
        logger.error(f"[FaceTrack] FAILED: {e}")
        logger.error(traceback.format_exc())
        
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except:
                pass
        
        return reframe_to_portrait(input_path, output_name)