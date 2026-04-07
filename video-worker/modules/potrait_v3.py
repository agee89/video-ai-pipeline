import cv2
import numpy as np
import mediapipe as mp
import json
import subprocess
import os
import logging
import sys
import math
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

# === CONFIGURATION & CONSTANTS ===
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("portrait")

@dataclass
class PortraitConfig:
    LIP_THRESHOLD: float = 12.0         # Minimum lip vertical opening (pixels)
    LIP_RATIO_THRESHOLD: float = 0.25   # Aspect ratio threshold
    AUDIO_RMS_THRESHOLD: float = 0.015  # Silence threshold for RMS
    LOOKAHEAD_FRAMES: int = 5           # Frames to look ahead for camera movement
    
    # Safe Zoom Rules (Perbaikan.md)
    ZOOM_LARGE_FACE_MAX: float = 1.05   # If width > 35%
    ZOOM_NORMAL_MAX: float = 1.15       # If width <= 35%
    FACE_WIDTH_THRESHOLD: float = 0.35  # 35% of frame width
    
    SMOOTHING_WINDOW: int = 61          # Window for Savitzky-Golay (must be odd)
    SMOOTHING_POLYORDER: int = 2        # Poly order for Savitzky-Golay
    
    # V4 Hysteresis
    HYSTERESIS_FACTOR: float = 1.5      # New speaker score must be X times better
    SCORE_MOMENTUM: float = 0.8         # Mixing factor for score smoothing
    MIN_CONSECUTIVE_FRAMES: int = 4     # Debounce

@dataclass
class FaceData:
    frame_idx: int
    face_id: int
    center_x: float
    center_y: float
    width: float
    height: float
    lip_activity: float
    raw_box: Tuple[float, float, float, float]  # x, y, w, h relative

@dataclass
class CameraState:
    crop_center_x: int
    zoom: float
    is_cut: bool

# === PASS 1: AUDIO ANALYSIS ===
class AudioAnalyzer:
    @staticmethod
    def analyze(video_path: str, fps: float, total_frames: int) -> List[float]:
        """
        Extracts audio and returns normalized RMS vector (0.0 - 1.0).
        """
        try:
            # 1. Extract raw PCM audio
            cmd = [
                'ffmpeg', '-i', video_path,
                '-f', 's16le', '-ac', '1', '-ar', '16000',  # 16kHz mono
                '-vn', 'pipe:1'
            ]
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            raw_audio, _ = process.communicate()
            
            audio_data = np.frombuffer(raw_audio, dtype=np.int16)
            
            # 2. Map audio samples to video frames
            samples_per_frame = int(16000 / fps)
            rms_map = [0.0] * total_frames
            
            for i in range(min(total_frames, len(audio_data) // samples_per_frame)):
                start = i * samples_per_frame
                end = start + samples_per_frame
                chunk = audio_data[start:end]
                
                if len(chunk) == 0:
                    continue
                    
                # Calculate RMS
                rms = np.sqrt(np.mean(chunk.astype(float)**2))
                # Normalize (16-bit audio max is 32768)
                norm_rms = rms / 32768.0
                rms_map[i] = float(norm_rms)
            
            # Simple Smoothing for Audio Curve
            rms_map = np.convolve(rms_map, np.ones(5)/5, mode='same').tolist()
            
            logger.info(f"[Audio] Audio Analysis Complete. Mean RMS: {np.mean(rms_map):.4f}")
            return rms_map
            
        except Exception as e:
            logger.error(f"[Audio] Extraction failed: {e}. Defaulting to SILENCE (0.0).")
            return [0.0] * total_frames

# === PASS 1: FACE TRAJECTORY ANALYSIS (NO BUCKETS) ===
class FaceTrajectoryAnalyzer:
    def __init__(self):
        self.mp_face_mesh = mp.solutions.face_mesh
        self.face_tracks: Dict[int, List[FaceData]] = {}  # face_id -> history
        self.next_face_id = 0
        self.active_faces: Dict[int, int] = {} # face_id -> last_seen_frame
        
    def analyze(self, video_path: str, width: int, height: int) -> Dict[int, List[FaceData]]:
        cap = cv2.VideoCapture(video_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        logger.info("[Vision] Starting Face Trajectory Analysis...")
        
        with self.mp_face_mesh.FaceMesh(
            max_num_faces=5,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        ) as face_mesh:
            
            frame_idx = 0
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break
                
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = face_mesh.process(rgb)
                
                current_frame_faces = []
                
                if results.multi_face_landmarks:
                    for landmarks in results.multi_face_landmarks:
                        # Extract metrics
                        raw_data = self._extract_face_metrics(landmarks, width, height, frame_idx)
                        current_frame_faces.append(raw_data)
                
                # Assign IDs (Simple Tracking by Distance)
                self._update_tracks(current_frame_faces, frame_idx)
                
                frame_idx += 1
                if frame_idx % 500 == 0:
                    logger.info(f"[Vision] Processed {frame_idx}/{total_frames} frames")
        
        cap.release()
        return self.face_tracks
    
    def _extract_face_metrics(self, landmarks, w, h, frame_idx) -> FaceData:
        # Bounding Box Refined
        xs = [lm.x for lm in landmarks.landmark]
        ys = [lm.y for lm in landmarks.landmark]
        x_min, x_max = min(xs) * w, max(xs) * w
        y_min, y_max = min(ys) * h, max(ys) * h
        
        box_w, box_h = x_max - x_min, y_max - y_min
        center_x, center_y = (x_min + x_max) / 2, (y_min + y_max) / 2
        
        # Lip Activity Calculation (Strict)
        upper = landmarks.landmark[13].y * h
        lower = landmarks.landmark[14].y * h
        
        # Corners (Mouth width)
        left = landmarks.landmark[61].x * w
        right = landmarks.landmark[291].x * w
        
        vertical_open = abs(upper - lower)
        mouth_width = abs(right - left) + 1e-6
        
        aspect_ratio = vertical_open / mouth_width
        
        lips = 0.0
        # Strict visual filter logic from Perbaikan.md implied contexts
        if vertical_open > PortraitConfig.LIP_THRESHOLD and aspect_ratio > PortraitConfig.LIP_RATIO_THRESHOLD:
            lips = vertical_open
        
        return FaceData(
            frame_idx=frame_idx,
            face_id=-1, # Pending assignment
            center_x=center_x,
            center_y=center_y,
            width=box_w,
            height=box_h,
            lip_activity=lips,
            raw_box=(x_min, y_min, box_w, box_h)
        )

    def _update_tracks(self, current_faces: List[FaceData], frame_idx: int):
        # Match current faces to existing active tracks
        used_indices = set()
        
        # Greedy matching by distance
        for face_id, last_seen in list(self.active_faces.items()):
            # If track is stale (>30 frames lost), drop it from active consideration
            if frame_idx - last_seen > 30:
                continue
            
            # Get last known position
            last_pos = self.face_tracks[face_id][-1]
            
            best_dist = 100000
            best_idx = -1
            
            for i, curr in enumerate(current_faces):
                if i in used_indices: continue
                
                dist = math.hypot(curr.center_x - last_pos.center_x, curr.center_y - last_pos.center_y)
                
                # Threshold for same face movement (e.g. max 200px jump)
                if dist < 200: 
                    if dist < best_dist:
                        best_dist = dist
                        best_idx = i
            
            if best_idx != -1:
                # Match Found
                current_faces[best_idx].face_id = face_id
                self.face_tracks[face_id].append(current_faces[best_idx])
                self.active_faces[face_id] = frame_idx
                used_indices.add(best_idx)
        
        # Create new tracks for unmatched faces
        for i, curr in enumerate(current_faces):
            if i not in used_indices:
                curr.face_id = self.next_face_id
                self.face_tracks[self.next_face_id] = [curr]
                self.active_faces[self.next_face_id] = frame_idx
                self.next_face_id += 1

# === PASS 1: SPEAKER CONFIRMATION & PASS 2: CAMERA PATH ===
class CameraPathGenerator:
    @staticmethod
    def generate(width: int, height: int, total_frames: int, 
                 audio_rms: List[float], 
                 face_tracks: Dict[int, List[FaceData]]) -> List[CameraState]:
        
        # 1. Resolve Speaker Per Frame (V4: Hysteresis Score)
        speaker_map = [-1] * total_frames 
        
        # Organize tracks
        frame_faces: Dict[int, List[FaceData]] = {}
        for fid, track in face_tracks.items():
            for face in track:
                if face.frame_idx not in frame_faces:
                    frame_faces[face.frame_idx] = []
                frame_faces[face.frame_idx].append(face)
        
        # Tracking state
        current_speaker_id = -1
        current_speaker_score = 0.0
        consecutive_frames = 0
        
        for i in range(total_frames):
            faces = frame_faces.get(i, [])
            rms = audio_rms[i]
            
            # Global silence check
            is_silence = rms < PortraitConfig.AUDIO_RMS_THRESHOLD
            
            best_fid = -1
            best_score = 0.0
            
            # Score all faces in view
            for f in faces:
                # Score = LipActivity * AudioRMS
                # If silent, score is basically 0
                
                # Base score: Lip motion * Audio * Size factor
                # We weight lip activity heavily
                score = f.lip_activity * (rms * 100.0)
                
                # Boost if face is large (main subject)
                face_ratio = f.width / width
                if face_ratio > 0.3:
                    score *= 1.5
                
                if score > best_score:
                    best_score = score
                    best_fid = f.face_id
            
            # Decision Logic (Hysteresis)
            if best_fid != -1 and not is_silence:
                if current_speaker_id == -1:
                    # No current speaker, take the best if it has decent score
                    if best_score > 50.0: # Arbitrary score threshold
                         current_speaker_id = best_fid
                         current_speaker_score = best_score
                         consecutive_frames = 1
                else:
                    # We have a current speaker.
                    # Switch ONLY if new speaker is SIGNIFICANTLY better
                    is_same = (best_fid == current_speaker_id)
                    
                    if is_same:
                        # Update current score with momentum
                        current_speaker_score = current_speaker_score * 0.8 + best_score * 0.2
                        consecutive_frames += 1
                    else:
                        # New candidate
                        threshold = current_speaker_score * PortraitConfig.HYSTERESIS_FACTOR
                        if best_score > threshold:
                            # Switch!
                            current_speaker_id = best_fid
                            current_speaker_score = best_score
                            consecutive_frames = 1
                        else:
                            # Stick with old speaker if possible (if still in frame)
                            # Or decay score
                            current_speaker_score *= 0.95
            else:
                 # Silence or emptiness
                 current_speaker_score *= 0.9 # Decay
            
            # Assign map (Hold logic)
            if current_speaker_id != -1:
                # Check if current_speaker is actually visible
                curr_visible = any(f.face_id == current_speaker_id for f in faces)
                if curr_visible:
                    speaker_map[i] = current_speaker_id
                else:
                    # Lost visual. Keep ID but mark as lost for pathing to decide?
                    # For now just hold ID in map, path generator will handle coordinates
                    speaker_map[i] = current_speaker_id
        
        # 2. Generate Raw Path (Trajectory + Backfill)
        raw_path_x = []
        raw_path_zoom = []
        
        # SCAN-AHEAD INIT (V13 Fix):
        # Instead of defaulting to width/2, we scan ahead to find the FIRST detected speaker.
        # We set default_x to that speaker's position.
        # This guarantees that even frame 0 starts at the face, not center.
        
        default_x = width / 2
        
        first_speaker_idx = -1
        for i in range(total_frames):
            if speaker_map[i] != -1:
                first_speaker_idx = i
                break
        
        if first_speaker_idx != -1:
             # Find the face for this speaker
             sid = speaker_map[first_speaker_idx]
             
             # Look in current frame or lookahead
             faces = frame_faces.get(first_speaker_idx, [])
             target_f = next((f for f in faces if f.face_id == sid), None)
             
             if target_f:
                 default_x = target_f.center_x
                 logger.info(f"[Backfill] Found start face at frame {first_speaker_idx}: {default_x}")
        
        # State persistence 
        last_known_x = default_x
        last_known_zoom = 1.0
        
        if first_speaker_idx != -1:
             # Pre-seed last_known so it doesn't drift if first frame is empty
             # We assume zoom 1.0 or heuristic
             pass
        
        has_initialized = False
        
        # Forward Pass
        for i in range(total_frames):
            speaker_id = speaker_map[i]
            
            # Start with last known to prevent jitter/drops
            target_x = last_known_x
            target_zoom = last_known_zoom
            
            found_target = False
            
            if speaker_id != -1:
                # Lookahead logic
                lookahead_idx = min(i + PortraitConfig.LOOKAHEAD_FRAMES, total_frames - 1)
                
                # Check frame at lookahead
                future_faces = frame_faces.get(lookahead_idx, [])
                target_f = next((f for f in future_faces if f.face_id == speaker_id), None)
                
                if not target_f:
                    # Fallback to current frame
                    faces = frame_faces.get(i, [])
                    target_f = next((f for f in faces if f.face_id == speaker_id), None)
                    
                if target_f:
                    target_x = target_f.center_x
                    found_target = True
                    
                    # Safe Zoom
                    face_ratio = target_f.width / width
                    if face_ratio > PortraitConfig.FACE_WIDTH_THRESHOLD:
                        target_zoom = PortraitConfig.ZOOM_LARGE_FACE_MAX
                    else:
                        target_zoom = PortraitConfig.ZOOM_NORMAL_MAX
            
            if found_target:
                last_known_x = target_x
                last_known_zoom = target_zoom
                has_initialized = True
                     
            raw_path_x.append(target_x)
            raw_path_zoom.append(target_zoom)

        # 3. Post-Processing: Robust Forward-Backward Fill (Fix Start/End Slide)
        # The loop above effectively holds the LAST value, fixing the "End Slide".
        # Now we must fix the "Start Slide" (before first detection).
        
        # Find first index where speaker_map was valid (or where we actually found a target)
        # Since we updated raw_path_x with actual values, we can just look for the first non-default 
        # BUT if the face is exactly at center, that fails.
        # Better: Scan speaker_map for first valid ID.
        
        first_valid_idx = -1
        for i in range(total_frames):
             if speaker_map[i] != -1:
                 first_valid_idx = i
                 break
        
        if first_valid_idx != -1:
             # Get the coordinate at that valid frame
             # Note: raw_path_x[first_valid_idx] might be lookahead result, which is good.
             start_val_x = raw_path_x[first_valid_idx]
             start_val_z = raw_path_zoom[first_valid_idx]
             
             # Backfill 0 -> first_valid_idx
             for k in range(first_valid_idx):
                 raw_path_x[k] = start_val_x
                 raw_path_zoom[k] = start_val_z
        
        # Explicit End Lock (just to be safe against lookahead jitter at very end)
        last_valid_idx = -1
        for i in range(total_frames - 1, -1, -1):
            if speaker_map[i] != -1:
                last_valid_idx = i
                break
                
        if last_valid_idx != -1 and last_valid_idx < total_frames - 1:
             end_val_x = raw_path_x[last_valid_idx]
             end_val_z = raw_path_zoom[last_valid_idx]
             for k in range(last_valid_idx + 1, total_frames):
                 raw_path_x[k] = end_val_x
                 raw_path_zoom[k] = end_val_z

        # 4. Global Smoothing
        smooth_x = CameraPathGenerator._smooth_signal(raw_path_x)
        smooth_zoom = CameraPathGenerator._smooth_signal(raw_path_zoom)
        
        # NUCLEAR OPTION V13.1: Post-Smoothing Edge Freeze
        # Savitzky-Golay can introduce "ringing" or "runge phenomenon" at edges even with nearest mode.
        # To strictly satisfy "No Slide at Start/End", we brutally lock the first/last second.
        
        # Freeze Start (30 frames ~ 1 sec)
        if total_frames > 60:
            freeze_frames = min(30, total_frames // 4)
            start_lock_val_x = smooth_x[freeze_frames]
            start_lock_val_z = smooth_zoom[freeze_frames]
            
            for k in range(freeze_frames):
                smooth_x[k] = start_lock_val_x
                smooth_zoom[k] = start_lock_val_z
                
            # Freeze End
            end_lock_pos = total_frames - freeze_frames
            end_lock_val_x = smooth_x[end_lock_pos]
            end_lock_val_z = smooth_zoom[end_lock_pos]
            
            for k in range(end_lock_pos, total_frames):
                smooth_x[k] = end_lock_val_x
                smooth_zoom[k] = end_lock_val_z
            
            logger.info(f"[V13.1] Edge Freeze Applied: Locked first/last {freeze_frames} frames.")
        
        final_states = []
        target_w_9_16 = int(height * 9 / 16)
        
        for i in range(total_frames):
            zoom = smooth_zoom[i]
             # Apply C lamped Zoom
            curr_zoom = max(1.0, zoom)
            
            vis_w = target_w_9_16 / curr_zoom
            view_w = int(vis_w)
            
            # Center calculation
            center = smooth_x[i]
            
            # Simple Crop X
            crop_x = center - (view_w / 2)
            
            final_states.append(CameraState(
                crop_center_x=int(crop_x),
                zoom=curr_zoom,
                is_cut=False
            ))
            
        return final_states

    @staticmethod
    def _smooth_signal(data: List[float]) -> List[float]:
        try:
            from scipy.signal import savgol_filter
            # Use 'nearest' mode to handle edges without zero-padding artifacts
            return savgol_filter(data, PortraitConfig.SMOOTHING_WINDOW, PortraitConfig.SMOOTHING_POLYORDER, mode='nearest').tolist()
        except ImportError:
            window = PortraitConfig.SMOOTHING_WINDOW
            return np.convolve(data, np.ones(window)/window, mode='same').tolist()

# === OPTIMIZED REFRAME FUNCTION ===
def reframe_to_portrait_with_face_tracking(input_path: str, output_name: str, *args, **kwargs) -> str:
    """
    Main entry point V4
    """
    output_temp = f"/app/output/{output_name}_temp.mp4"
    final_output = f"/app/output/{output_name}.mp4"
    
    try:
        logger.info(f"=== PORTRAIT AUTO V4 START: {input_path} ===")
        
        # 1. Video Info
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
             raise Exception("Cannot open input video")
             
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        
        # 2. Pass 1: Audio (RMS Float)
        logger.info("--- PASS 1: AUDIO (Continuous RMS) ---")
        audio_rms = AudioAnalyzer.analyze(input_path, fps, total_frames)
        
        # 3. Pass 1: Vision (Trajectories)
        logger.info("--- PASS 1: VISION TRAJECTORIES ---")
        analyzer = FaceTrajectoryAnalyzer()
        face_tracks = analyzer.analyze(input_path, width, height)
        logger.info(f"Detected {len(face_tracks)} unique face tracks")
        
        # 4. Pass 2: Hysteresis Path Generation
        logger.info("--- PASS 2: PATH GENERATION (Hysteresis & Backfill) ---")
        camera_states = CameraPathGenerator.generate(width, height, total_frames, audio_rms, face_tracks)
        
        # 5. Rendering
        logger.info(f"--- RENDERING ({total_frames} frames) ---")
        cap = cv2.VideoCapture(input_path)
        
        target_h = height
        target_w = int(target_h * 9 / 16)
        if target_w > width:
            target_w = width
            target_h = int(target_w * 16 / 9)
            
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_temp, fourcc, fps, (target_w, target_h))
        
        idx = 0
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret: break
            
            if idx < len(camera_states):
                state = camera_states[idx]
                
                curr_zoom = state.zoom
                view_w = int(target_w / curr_zoom)
                view_h = int(target_h / curr_zoom)
                
                # STRICT BOUNDARY CLAMPING
                if view_w > width: view_w = width
                if view_h > height: view_h = height
                
                x = int(state.crop_center_x)
                y = (height - view_h) // 2 
                x = max(0, min(x, width - view_w))
                y = max(0, min(y, height - view_h))
                
                crop = frame[y:y+view_h, x:x+view_w]
                if crop.size == 0: crop = frame
                    
                if crop.shape[0] != target_h or crop.shape[1] != target_w:
                    crop = cv2.resize(crop, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)
                
                out.write(crop)
            idx += 1
            if idx % 200 == 0:
                 logger.info(f"Rendered {idx}/{total_frames}")
                 
        cap.release()
        out.release()
        
        # 6. Audio Muxing
        logger.info("--- MUXING AUDIO ---")
        if os.path.exists(final_output): os.remove(final_output)
            
        cmd = [
            'ffmpeg', '-y', '-loglevel', 'error',
            '-i', output_temp, '-i', input_path,
            '-map', '0:v:0', '-map', '1:a:0?',
            '-c:v', 'libx264', '-preset', 'slow', '-crf', '18',
            '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '192k',
            '-movflags', '+faststart',
            final_output
        ]
        subprocess.run(cmd, check=True)
        if os.path.exists(output_temp): os.remove(output_temp)
            
        logger.info("=== PORTRAIT V4 COMPLETE ===")
        return final_output

    except Exception as e:
        logger.error(f"Portrait V4 Fatal Error: {e}")
        logger.error(f"Traceback: {logger.exception(e)}")
        return reframe_to_portrait(input_path, output_name)

def reframe_to_portrait(input_path, output_name):
    output_path = f"/app/output/{output_name}.mp4"
    cmd = [
        'ffmpeg', '-i', input_path,
        '-vf', 'crop=ih*(9/16):ih,scale=1080:1920',
        '-c:v', 'libx264', '-y', output_path
    ]
    subprocess.run(cmd)
    return output_path