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


def reframe_to_portrait_with_face_tracking(input_path: str, output_name: str, sensitivity: int = 5, camera_smoothing: float = 0.15) -> str:
    """
    Portrait dengan face tracking menggunakan HYBRID approach:
    1. Face Detection (untuk wide shot, bekerja dari jarak jauh)
    2. Face Mesh (untuk close-up, deteksi bibir)
    
    Selalu fokus pada salah satu orang, prioritas yang lebih aktif.
    
    Args:
        sensitivity: 1-10, controls how quickly camera switches between faces
        camera_smoothing: 0.05-0.5, higher = faster camera movement (default 0.15)
    """
    import traceback
    
    output_path = f"/app/output/{output_name}_temp.mp4"
    final_output = f"/app/output/{output_name}.mp4"
    
    # Use camera_smoothing directly (0.05 - 0.5)
    smoothing_factor = max(0.05, min(0.5, camera_smoothing))
    
    logger.info(f"[FaceTrack] Starting (sensitivity={sensitivity}, camera_smoothing={smoothing_factor:.3f})")
    
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
            min_detection_confidence=0.4  # Increased from 0.3 for better accuracy
        )
        
        # 2. Face Mesh - for lip tracking on close-up faces
        mp_face_mesh = mp.solutions.face_mesh
        face_mesh = mp_face_mesh.FaceMesh(
            max_num_faces=6,  # Increased to detect more faces
            min_detection_confidence=0.4,  # Increased from 0.3
            min_tracking_confidence=0.4
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
        tracked_face_bucket = None
        smooth_crop_x = None
        frames_since_face_seen = 0  # Count frames since tracked face was last seen
        max_frames_without_face = 15  # After this many frames, reset and find new face
        
        # Activity scores per face (by approximate X position bucket)
        # More buckets = finer tracking of individual faces
        NUM_BUCKETS = 12  # Increased for better multi-person tracking
        BUCKET_WIDTH = width // NUM_BUCKETS
        face_activity = {}  # bucket -> activity score
        face_last_seen = {}  # bucket -> last frame detected
        face_positions = {}  # bucket -> last known x position
        face_prev_positions = {}  # bucket -> previous x position (for movement detection)
        
        # === SUSTAINED ACTIVITY TRACKING ===
        # Dynamically adjust based on sensitivity
        # Sensitivity 1 = 3 seconds, Sensitivity 10 = 0.5 seconds
        sustained_time = 3.0 - (sensitivity - 1) * 0.28  # 3.0s -> 0.48s
        sustained_time = max(0.5, min(3.0, sustained_time))
        sustained_frames_required = int(fps * sustained_time)
        
        # Switch cooldown - also dynamic
        # Sensitivity 1 = 2 seconds, Sensitivity 10 = 0.5 seconds
        cooldown_time = 2.0 - (sensitivity - 1) * 0.17  # 2.0s -> 0.47s
        cooldown_time = max(0.5, min(2.0, cooldown_time))
        switch_cooldown_frames = int(fps * cooldown_time)
        
        face_sustained_activity = {}  # bucket -> consecutive frames of high activity
        
        # Lock mode - when locked on active person, stay locked
        is_locked_on_active = False  # True when focused on an actively speaking person
        lock_activity_threshold = 2.0  # Minimum activity to maintain lock
        
        # Switch threshold based on sensitivity (1-10)
        # Higher sensitivity = easier to switch (lower threshold)
        switch_threshold = 2.0 - (sensitivity - 1) * 0.15  # 2.0 -> 0.65
        switch_threshold = max(1.2, min(2.0, switch_threshold))
        
        logger.info(f"[FaceTrack] Sensitivity {sensitivity}: sustained={sustained_time:.1f}s, cooldown={cooldown_time:.1f}s, threshold={switch_threshold:.2f}")
        
        # Detection settings - more frequent for better tracking
        detect_interval = max(1, int(fps / 10))  # 10 times per second (was 8)
        
        frame_count = 0
        max_frames = int(fps * 300)
        detection_count = 0
        mesh_count = 0
        last_switch_frame = 0  # Track when last switch happened
        
        # === DYNAMIC ZOOM STATE ===
        # Zoom in when mouth is wide open (laughing, surprised)
        current_zoom = 1.0  # 1.0 = no zoom, 1.25 = 25% zoom in
        target_zoom = 1.0
        max_zoom = 1.25  # Maximum 25% zoom in (increased from 15%)
        zoom_smoothing = 0.08  # Faster zoom transitions (was 0.05)
        
        # Mouth opening thresholds (in pixels, relative to face height)
        # Normal talking: 5-15 pixels, Wide open: 20+ pixels
        mouth_open_threshold = 15  # Lowered to trigger zoom earlier
        mouth_very_open_threshold = 22  # Lowered for max zoom
        
        # Track mouth opening history for smoothing
        mouth_opening_history = []
        max_mouth_history = 5  # Average over 5 detections
        
        logger.info(f"[FaceTrack] Processing (detect every {detect_interval} frames, switch_threshold={switch_threshold:.2f})...")
        
        # === INITIAL FACE SCAN ===
        # Scan first ~1 second to find MOST ACTIVE face (not largest!)
        # This prevents locking onto silent center person
        logger.info("[FaceTrack] Scanning for most ACTIVE face (not largest)...")
        initial_scan_frames = min(int(fps * 1.0), total_frames)  # ~1 second
        
        # Track activity for each face position
        initial_face_positions = {}  # bucket -> list of x positions
        initial_face_sizes = {}  # bucket -> average size
        
        for scan_i in range(initial_scan_frames):
            ret, scan_frame = cap.read()
            if not ret:
                break
            
            scan_rgb = cv2.cvtColor(scan_frame, cv2.COLOR_BGR2RGB)
            scan_results = face_detector.process(scan_rgb)
            
            if scan_results.detections:
                for detection in scan_results.detections:
                    bbox = detection.location_data.relative_bounding_box
                    face_x = int((bbox.xmin + bbox.width / 2) * width)
                    face_size = bbox.width * bbox.height * width * height
                    
                    # Assign to bucket
                    bucket = min(face_x // BUCKET_WIDTH, NUM_BUCKETS - 1)
                    
                    if bucket not in initial_face_positions:
                        initial_face_positions[bucket] = []
                        initial_face_sizes[bucket] = []
                    
                    initial_face_positions[bucket].append(face_x)
                    initial_face_sizes[bucket].append(face_size)
        
        # Calculate movement (activity) for each face bucket
        best_initial_face = None
        best_initial_movement = 0
        
        for bucket, positions in initial_face_positions.items():
            if len(positions) < 3:
                continue
            
            # Calculate total movement (sum of position changes)
            movement = sum(abs(positions[i] - positions[i-1]) for i in range(1, len(positions)))
            avg_x = sum(positions) / len(positions)
            avg_size = sum(initial_face_sizes[bucket]) / len(initial_face_sizes[bucket])
            
            logger.info(f"[FaceTrack] Bucket {bucket}: movement={movement:.0f}, avg_x={avg_x:.0f}")
            
            # Pick face with MOST MOVEMENT (activity)
            if movement > best_initial_movement:
                best_initial_movement = movement
                best_initial_face = {
                    'x': avg_x,
                    'size': avg_size,
                    'bucket': bucket,
                    'movement': movement
                }
        
        # If no movement detected, fall back to center area
        if best_initial_face is None and initial_face_positions:
            # Pick the face closest to center as fallback
            center_bucket = NUM_BUCKETS // 2
            closest_bucket = min(initial_face_positions.keys(), key=lambda b: abs(b - center_bucket))
            positions = initial_face_positions[closest_bucket]
            avg_x = sum(positions) / len(positions)
            avg_size = sum(initial_face_sizes[closest_bucket]) / len(initial_face_sizes[closest_bucket])
            best_initial_face = {
                'x': avg_x,
                'size': avg_size,
                'bucket': closest_bucket,
                'movement': 0
            }
            logger.info(f"[FaceTrack] No movement, fallback to bucket {closest_bucket}")
        
        # Reset video to beginning
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        
        # Set initial tracking position
        if best_initial_face:
            tracked_face_x = float(best_initial_face['x'])
            tracked_face_bucket = best_initial_face['bucket']
            smooth_crop_x = float(tracked_face_x - target_width // 2)
            smooth_crop_x = max(0, min(smooth_crop_x, width - target_width))
            logger.info(f"[FaceTrack] Initial lock: bucket={best_initial_face['bucket']}, x={best_initial_face['x']:.0f}, movement={best_initial_face['movement']:.0f}")
        else:
            # No face found in scan - default to center
            tracked_face_x = float(width // 2)
            tracked_face_bucket = NUM_BUCKETS // 2
            smooth_crop_x = float((width - target_width) // 2)
            logger.warning("[FaceTrack] No face in initial scan, using center")
        
        
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
                            face_y = int((bbox.ymin + bbox.height / 2) * height)
                            face_size = bbox.width * bbox.height * width * height
                            
                            # Calculate bucket for this face
                            bucket = min(face_x // BUCKET_WIDTH, NUM_BUCKETS - 1)
                            
                            # Update last seen
                            face_last_seen[bucket] = frame_count
                            
                            # Calculate movement since last frame (body/head movement detection)
                            movement = 0
                            if bucket in face_positions:
                                prev_x = face_positions[bucket]
                                movement = abs(face_x - prev_x)
                            
                            # Store previous position before updating
                            if bucket in face_positions:
                                face_prev_positions[bucket] = face_positions[bucket]
                            face_positions[bucket] = face_x
                            
                            # Initialize activity if new face
                            if bucket not in face_activity:
                                face_activity[bucket] = 0
                            
                            # Add movement to activity (movement = active person)
                            # Higher movement = more active
                            movement_score = min(movement / 10.0, 5.0)  # Cap at 5 pixels movement contribution
                            
                            faces_this_frame.append({
                                'x': face_x,
                                'y': face_y,
                                'size': face_size,
                                'bucket': bucket,
                                'lip_activity': 0,
                                'movement': movement_score
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
                            
                            # Find matching detected face for this mesh
                            matched_face = None
                            for f in faces_this_frame:
                                if abs(f['x'] - mesh_face_x) < BUCKET_WIDTH * 1.5:
                                    matched_face = f
                                    f['lip_activity'] = lip_open
                                    break
                            
                            # === EXPRESSION-BASED ZOOM ===
                            # Check if this is the tracked face and mouth is wide open
                            is_tracked_face = (
                                tracked_face_bucket is not None and 
                                abs(mesh_bucket - tracked_face_bucket) <= 1
                            )
                            
                            if is_tracked_face:
                                # Track mouth opening for zoom
                                mouth_opening_history.append(lip_open)
                                if len(mouth_opening_history) > max_mouth_history:
                                    mouth_opening_history.pop(0)
                                
                                # Calculate average mouth opening
                                avg_mouth_open = sum(mouth_opening_history) / len(mouth_opening_history)
                                
                                # Determine target zoom based on mouth opening
                                if avg_mouth_open >= mouth_very_open_threshold:
                                    # Very wide open - max zoom (laughing/surprised)
                                    target_zoom = max_zoom
                                elif avg_mouth_open >= mouth_open_threshold:
                                    # Moderately open - partial zoom
                                    zoom_ratio = (avg_mouth_open - mouth_open_threshold) / (mouth_very_open_threshold - mouth_open_threshold)
                                    target_zoom = 1.0 + (max_zoom - 1.0) * zoom_ratio
                                else:
                                    # Normal - no zoom
                                    target_zoom = 1.0
                            
                            # Update activity based on lip opening + movement
                            if mesh_bucket in face_activity:
                                # Combined activity: lip opening + movement
                                movement_bonus = matched_face['movement'] if matched_face else 0
                                combined_activity = lip_open + movement_bonus
                                
                                # Faster activity accumulation (70/30 instead of 80/20)
                                face_activity[mesh_bucket] = 0.7 * face_activity[mesh_bucket] + 0.3 * combined_activity
                    
                    # STEP 3: Determine which face to track
                    if faces_this_frame:
                        # Decay activity for faces not seen recently (faster decay)
                        current_time = frame_count
                        for b in list(face_activity.keys()):
                            if b not in face_last_seen or current_time - face_last_seen[b] > fps * 1.5:
                                face_activity[b] *= 0.8  # Faster decay (was 0.9)
                        
                        # Track best candidates
                        best_face = None
                        best_score = -1
                        largest_face = None
                        largest_size = 0
                        most_active_face = None
                        highest_activity = 0
                        
                        for f in faces_this_frame:
                            bucket = f['bucket']
                            activity = face_activity.get(bucket, 0)
                            
                            # Track largest face as fallback
                            if f['size'] > largest_size:
                                largest_size = f['size']
                                largest_face = f
                            
                            # Track most active face (speaking/moving)
                            current_activity = activity + f['lip_activity'] * 2 + f['movement']
                            
                            # === UPDATE SUSTAINED ACTIVITY ===
                            # Track how long this face has been consistently active
                            if current_activity > 2.0:  # Threshold for "active"
                                face_sustained_activity[bucket] = face_sustained_activity.get(bucket, 0) + 1
                            else:
                                # Reset if not active (brief pause = reset)
                                face_sustained_activity[bucket] = max(0, face_sustained_activity.get(bucket, 0) - 2)
                            
                            # Only consider as "most active" if sustained
                            sustained = face_sustained_activity.get(bucket, 0)
                            if current_activity > highest_activity and sustained >= sustained_frames_required // 2:
                                highest_activity = current_activity
                                most_active_face = f
                            
                            # Combined score: ACTIVITY IS NOW PRIORITY
                            # Reduce size weight when multiple people in frame
                            num_faces = len(faces_this_frame)
                            if num_faces >= 3:
                                # Many faces: size almost irrelevant, activity is everything
                                size_divisor = 500000
                            elif num_faces == 2:
                                # Two faces: size has minimal influence
                                size_divisor = 300000
                            else:
                                # Single face: size helps with centering
                                size_divisor = 150000
                            
                            activity_score = activity * 1.5 + f['lip_activity'] * 2.5 + f['movement'] * 1.0
                            size_score = f['size'] / size_divisor
                            
                            score = activity_score + size_score
                            
                            if score > best_score:
                                best_score = score
                                best_face = f
                        
                        # IMPORTANT: If there's a clearly active face WITH SUSTAINED activity, prefer it
                        # This ensures active speakers beat silent large faces
                        if most_active_face and highest_activity > 3.0:
                            sustained = face_sustained_activity.get(most_active_face['bucket'], 0)
                            if sustained >= sustained_frames_required:  # Must be active for sustained_frames_required
                                if best_face != most_active_face:
                                    best_activity = face_activity.get(best_face['bucket'], 0) if best_face else 0
                                    most_activity = face_activity.get(most_active_face['bucket'], 0)
                                    
                                    if most_activity > best_activity + 2.0 or highest_activity > 5.0:
                                        best_face = most_active_face
                        
                        # Only fallback to largest if NO activity detected at all
                        if best_face and largest_face and highest_activity < 1.0:
                            best_activity = face_activity.get(best_face['bucket'], 0)
                            if best_activity < 0.3 and largest_face['size'] > best_face['size'] * 1.5:
                                best_face = largest_face
                        
                        if best_face:
                            # Update tracked face with smoothing
                            if tracked_face_x is None:
                                tracked_face_x = float(best_face['x'])
                                tracked_face_bucket = best_face['bucket']
                                last_switch_frame = frame_count
                                logger.info(f"[FaceTrack] Lock: x={best_face['x']}, size={best_face['size']:.0f}")
                                is_locked_on_active = highest_activity > lock_activity_threshold
                            else:
                                # Check cooldown - don't switch too frequently
                                cooldown_ok = (frame_count - last_switch_frame) >= switch_cooldown_frames
                                
                                # Check if should switch to another face
                                current_bucket = tracked_face_bucket if tracked_face_bucket is not None else min(int(tracked_face_x) // BUCKET_WIDTH, NUM_BUCKETS - 1)
                                current_activity = face_activity.get(current_bucket, 0)
                                current_sustained = face_sustained_activity.get(current_bucket, 0)
                                
                                # Update lock status based on current person's activity
                                if current_activity > lock_activity_threshold:
                                    is_locked_on_active = True
                                elif current_activity < 0.3 and current_sustained < sustained_frames_required // 2:
                                    is_locked_on_active = False
                                
                                # === AUTO ZOOM when locked on active speaker ===
                                if is_locked_on_active and current_activity > 1.5:
                                    target_zoom = min(max_zoom, 1.0 + current_activity * 0.02)
                                
                                # Get sustained activity for potential switch targets
                                best_sustained = face_sustained_activity.get(best_face['bucket'], 0)
                                most_active_sustained = face_sustained_activity.get(most_active_face['bucket'], 0) if most_active_face else 0
                                
                                # === SPECIAL: 2-PERSON DIALOG MODE ===
                                # When 2 people talking with high sensitivity, switch faster but STAY
                                num_faces = len(faces_this_frame)
                                is_two_person_dialog = (num_faces == 2 and sensitivity >= 7)
                                
                                # Minimum stay time after switch (prevents hesitation)
                                # Must stay at least 2.5 seconds before switching again
                                min_stay_frames = int(fps * 2.5)  # 2.5 seconds minimum stay
                                frames_since_switch = frame_count - last_switch_frame
                                can_instant_switch = frames_since_switch >= min_stay_frames
                                
                                # For 2-person dialog: faster switch when other is MUCH more active
                                # But requires minimum stay time to prevent back-and-forth
                                instant_dialog_switch = False
                                if is_two_person_dialog and most_active_face and can_instant_switch:
                                    other_bucket = most_active_face['bucket']
                                    if other_bucket != current_bucket:
                                        # Switch if other person is significantly more active
                                        # Must be at least 2x more active to switch
                                        if highest_activity > current_activity * 2.0 and highest_activity > 3.0:
                                            instant_dialog_switch = True
                                
                                # Normal mode: use sustained requirement
                                effective_sustained_required = sustained_frames_required
                                if is_two_person_dialog:
                                    effective_sustained_required = max(3, sustained_frames_required // 4)  # Much shorter
                                
                                # === LOCK MODE SWITCHING ===
                                can_switch = (
                                    cooldown_ok and
                                    (not is_locked_on_active or current_activity < 0.3)
                                )
                                
                                # Someone else has sustained activity
                                other_ready_to_switch = (
                                    most_active_face is not None and
                                    most_active_face['bucket'] != current_bucket and
                                    most_active_sustained >= effective_sustained_required and
                                    highest_activity > 3.0
                                )
                                
                                if (can_switch and other_ready_to_switch) or instant_dialog_switch:
                                    switch_type = "INSTANT" if instant_dialog_switch else "SWITCH"
                                    logger.info(f"[FaceTrack] {switch_type}: {current_bucket} -> {most_active_face['bucket']} (activity {current_activity:.1f} vs {highest_activity:.1f})")
                                    tracked_face_x = float(most_active_face['x'])
                                    tracked_face_bucket = most_active_face['bucket']
                                    last_switch_frame = frame_count
                                    is_locked_on_active = True  # Lock onto new active person
                                    target_zoom = max_zoom  # Zoom in when switching to active person
                                else:
                                    # === STAY LOCKED - MINIMAL POSITION DRIFT ===
                                    # Only update position slightly to follow same person
                                    found_match = False
                                    for f in faces_this_frame:
                                        bucket_match = f['bucket'] == current_bucket
                                        position_match = abs(f['x'] - tracked_face_x) < width // 6  # Tighter match
                                        
                                        if bucket_match or position_match:
                                            # VERY stable position update - only 5% drift
                                            tracked_face_x = 0.95 * tracked_face_x + 0.05 * f['x']
                                            frames_since_face_seen = 0  # Reset counter
                                            found_match = True
                                            break
                                    
                                    if not found_match:
                                        frames_since_face_seen += 1
                                        
                                        # === LOST FACE RECOVERY ===
                                        # If face lost for too long, switch to any visible face
                                        if frames_since_face_seen >= max_frames_without_face and faces_this_frame:
                                            # Find best new face to track
                                            new_face = largest_face or faces_this_frame[0]
                                            logger.info(f"[FaceTrack] RECOVERY: Lost face for {frames_since_face_seen} frames, switching to bucket {new_face['bucket']}")
                                            tracked_face_x = float(new_face['x'])
                                            tracked_face_bucket = new_face['bucket']
                                            frames_since_face_seen = 0
                                            is_locked_on_active = False
                                            target_zoom = 1.0  # Reset zoom when recovering
                    
                    else:
                        # No faces detected this frame
                        frames_since_face_seen += 1
                        if frames_since_face_seen >= max_frames_without_face:
                            target_zoom = 1.0  # Reset zoom when no faces
                
                except Exception as e:
                    logger.warning(f"[FaceTrack] Detection error at frame {frame_count}: {e}")
            
            # === SMOOTH ZOOM TRANSITION ===
            # Gradually transition current zoom toward target zoom
            current_zoom += zoom_smoothing * (target_zoom - current_zoom)
            current_zoom = max(1.0, min(max_zoom, current_zoom))
            
            # Calculate zoomed crop dimensions
            # Zoom in = smaller crop area from source = faces appear larger
            zoom_factor = 1.0 / current_zoom  # Inverse: 1.15 zoom = 0.87 of original area
            zoomed_width = int(target_width * zoom_factor)
            zoomed_height = int(target_height * zoom_factor)
            
            # Ensure zoomed dimensions are valid
            zoomed_width = min(zoomed_width, width)
            zoomed_height = min(zoomed_height, height)
            
            # === CALCULATE CROP POSITION ===
            if tracked_face_x is not None:
                target_crop_x = tracked_face_x - zoomed_width // 2
            else:
                # No face ever detected - use center (fallback)
                target_crop_x = (width - zoomed_width) // 2
            
            target_crop_x = max(0, min(target_crop_x, width - zoomed_width))
            
            # Initialize smooth crop
            if smooth_crop_x is None:
                smooth_crop_x = float(target_crop_x)
            
            # Smooth camera movement
            smooth_crop_x += smoothing_factor * (target_crop_x - smooth_crop_x)
            crop_x = int(smooth_crop_x)
            crop_x = max(0, min(crop_x, width - zoomed_width))
            
            crop_y = max(0, (height - zoomed_height) // 2)
            
            # Crop with zoom-adjusted dimensions
            cropped = frame[crop_y:crop_y+zoomed_height, crop_x:crop_x+zoomed_width]
            
            # Resize to target output size (this is where zoom effect becomes visible)
            if cropped.shape[0] != target_height or cropped.shape[1] != target_width:
                cropped = cv2.resize(cropped, (target_width, target_height), interpolation=cv2.INTER_LANCZOS4)
            
            out.write(cropped)
            frame_count += 1
            
            if frame_count % 300 == 0:
                face_str = f"{tracked_face_x:.0f}" if tracked_face_x else "none"
                zoom_str = f"{current_zoom:.2f}" if current_zoom > 1.01 else "1.0"
                logger.info(f"[FaceTrack] Frame {frame_count}/{total_frames}, x={face_str}, crop_x={crop_x}, zoom={zoom_str}")
        
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