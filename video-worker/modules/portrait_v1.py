import subprocess
import os
import json
import logging
import sys
import traceback
from dataclasses import dataclass
from typing import List, Optional, Tuple

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


# === NEW: Camera Path Logic ===

@dataclass
class CameraConfig:
    crop_x: int
    zoom: float
    is_cut: bool
    debug_info: str = ""

class CameraPathAnalyzer:
    def __init__(self, sensitivity: int = 5, smoothing: float = 0.15, zoom_threshold: float = 20.0, zoom_level: float = 1.15):
        self.sensitivity = sensitivity
        self.smoothing = max(0.05, min(0.5, smoothing))
        self.zoom_threshold = zoom_threshold
        self.zoom_max_level = zoom_level
        
        # Scene detection thresholds
        self.scene_diff_threshold = 30.0  # Pixel difference threshold
        
        # Internal state
        self.face_activity = {}
        self.tracked_bucket = None
        self.tracked_x = None  # Float for smooth tracking
        self.current_zoom = 1.0
        self.last_best_face = None
        
    def detect_scene_change(self, prev_frame, curr_frame) -> bool:
        """Detect if substantial scene change occurred"""
        try:
            import cv2
            import numpy as np
            if prev_frame is None:
                return True
                
            # Resize for speed
            small_h, small_w = 64, 64
            p_small = cv2.resize(prev_frame, (small_w, small_h))
            c_small = cv2.resize(curr_frame, (small_w, small_h))
            
            # Convert to gray
            p_gray = cv2.cvtColor(p_small, cv2.COLOR_BGR2GRAY)
            c_gray = cv2.cvtColor(c_small, cv2.COLOR_BGR2GRAY)
            
            # Calculate difference
            diff = cv2.absdiff(p_gray, c_gray)
            mean_diff = np.mean(diff)
            
            return mean_diff > self.scene_diff_threshold
        except Exception as e:
            logger.warning(f"[Analyzer] Scene detection error: {e}")
            return False

    def analyze(self, input_path: str, target_width: int, target_height: int) -> List[CameraConfig]:
        import cv2
        import mediapipe as mp
        import numpy as np
        
        logger.info(f"[Analyzer] Starting Pass 1: Analysis...")
        
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            raise Exception(f"Cannot open {input_path}")
            
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        # Setup detectors
        mp_face_detection = mp.solutions.face_detection
        face_detector = mp_face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.4)
        
        mp_face_mesh = mp.solutions.face_mesh
        face_mesh = mp_face_mesh.FaceMesh(max_num_faces=5, min_detection_confidence=0.4)
        
        path: List[CameraConfig] = []
        prev_frame = None
        
        # Bucketing
        NUM_BUCKETS = 12
        BUCKET_WIDTH = width // NUM_BUCKETS
        
        # Camera state
        # CHANGED: We now smooth the CENTER position, not the left crop edge.
        # This prevents "drifting" when the crop width changes during zoom.
        smooth_center_x = float(width / 2) 
        
        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
                
            is_cut = self.detect_scene_change(prev_frame, frame)
            
            if is_cut and frame_idx > 0:
                logger.info(f"[Analyzer] Scene Cut detected at frame {frame_idx}")
                # RESET tracking state
                self.tracked_bucket = None
                self.face_activity = {}
                self.tracked_x = None
                self.current_zoom = 1.0 
                self.last_best_face = None
            
            # --- Face Detection Logic ---
            detect_interval = max(1, int(fps / 10))
            faces_this_frame = []
            
            if frame_idx % detect_interval == 0 or is_cut:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                
                # 1. Detection
                results = face_detector.process(rgb)
                if results.detections:
                    for detection in results.detections:
                        bbox = detection.location_data.relative_bounding_box
                        face_x = int((bbox.xmin + bbox.width/2) * width)
                        bucket = min(face_x // BUCKET_WIDTH, NUM_BUCKETS - 1)
                        faces_this_frame.append({
                            'x': face_x, 'bucket': bucket, 'size': bbox.width * bbox.height,
                            'lip_activity': 0
                        })
                        
                # 2. Mesh (Lip Activity)
                mesh_results = face_mesh.process(rgb)
                if mesh_results.multi_face_landmarks:
                    for landmarks in mesh_results.multi_face_landmarks:
                        nose = landmarks.landmark[1]
                        mesh_x = int(nose.x * width)
                        upper = landmarks.landmark[13].y
                        lower = landmarks.landmark[14].y
                        lip_open = abs(upper - lower) * height
                        
                        # Match to face
                        for f in faces_this_frame:
                            if abs(f['x'] - mesh_x) < BUCKET_WIDTH:
                                f['lip_activity'] = lip_open
                                b = f['bucket']
                                self.face_activity[b] = 0.7 * self.face_activity.get(b,0) + 0.3 * lip_open
            
            # --- Target Selection ---
            if frame_idx % detect_interval == 0 or is_cut:
                best_face = None
                best_score = -1
                for f in faces_this_frame:
                    b = f['bucket']
                    activity = self.face_activity.get(b, 0)
                    score = activity * 2.0 + f['size'] * 10.0
                    if score > best_score:
                        best_score = score
                        best_face = f
                self.last_best_face = best_face
            
            best_face = getattr(self, 'last_best_face', None)
            
            # Determine Target X (CENTER)
            target_x = smooth_center_x # Default to current
            
            if best_face:
                if self.tracked_bucket is None:
                     self.tracked_bucket = best_face['bucket']
                     self.tracked_x = float(best_face['x'])
                else:
                    if best_face['bucket'] != self.tracked_bucket:
                        current_activity = self.face_activity.get(self.tracked_bucket, 0)
                        best_activity = self.face_activity.get(best_face['bucket'], 0)
                        if best_activity > current_activity * 2 + 0.5:
                            self.tracked_bucket = best_face['bucket']
                            self.tracked_x = float(best_face['x'])
                
                # Stabilization
                target_f = next((f for f in faces_this_frame if f['bucket'] == self.tracked_bucket), None)
                if target_f:
                    # Dynamic stabilization based on sensitivity
                    stab_factor = 0.02 + (self.sensitivity / 10.0) * 0.18
                    
                    if is_cut:
                         self.tracked_x = float(target_f['x'])
                    else:
                         self.tracked_x = (1.0 - stab_factor) * self.tracked_x + stab_factor * target_f['x']
                
                target_x = self.tracked_x

            elif self.tracked_x is not None:
                 target_x = self.tracked_x
            
            # --- Smoothing (CENTER) ---
            if is_cut:
                smooth_center_x = target_x
            else:
                smooth_center_x = smooth_center_x + self.smoothing * (target_x - smooth_center_x)
            
            # --- Zoom Calculation (Asymmetric) ---
            zoom_target = 1.0
            
            # User Feedback: Only zoom on distinct "laugh/surprise" (wide open), not small talk.
            # Raised threshold from 8.0 -> 20.0 to filter out normal speaking.
            # Reduced max zoom from 1.25 (25%) -> 1.15 (15%).
            if best_face and best_face['lip_activity'] > self.zoom_threshold: 
                 zoom_target = self.zoom_max_level
            
            if is_cut:
                self.current_zoom = 1.0
            else:
                # Asymmetric Zoom Speed: Fast Attack, Slow Decay
                if zoom_target > self.current_zoom:
                    zoom_speed = 0.25 # Fast Attack (Snap to expression)
                else:
                    zoom_speed = 0.04 # Slow Decay (Relax gently)
                self.current_zoom += zoom_speed * (zoom_target - self.current_zoom)

            # --- Final Box Calculation ---
            # Now we calculate the top-left crop based on the Smoothed Center and Smoothed Zoom
            current_vis_width = target_width / self.current_zoom
            final_crop_x = smooth_center_x - (current_vis_width / 2)
            
            # Apply bounds
            final_crop_x = max(0, min(final_crop_x, width - current_vis_width))
            
            # Record
            config = CameraConfig(
                crop_x=int(final_crop_x),
                zoom=self.current_zoom,
                is_cut=is_cut
            )
            path.append(config)
            
            prev_frame = frame.copy()
            frame_idx += 1
            if frame_idx % 200 == 0:
                logger.info(f"[Analyzer] Analyzed {frame_idx}/{total_frames}")

        cap.release()
        face_detector.close()
        face_mesh.close()
        return path

def reframe_to_portrait_with_face_tracking(input_path: str, output_name: str, sensitivity: int = 5, camera_smoothing: float = 0.15, zoom_threshold: float = 20.0, zoom_level: float = 1.15) -> str:
    output_path = f"/app/output/{output_name}_temp.mp4"
    final_output = f"/app/output/{output_name}.mp4"
    
    try:
        import cv2
        import mediapipe as mp
        import numpy as np
    except ImportError as e:
        logger.error(f"[FaceTrack] Import error: {e}")
        return reframe_to_portrait(input_path, output_name)
        
    try:
        # 1. Open Video for Info
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            raise Exception(f"Cannot open video: {input_path}")
        
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        
        # Target dimensions
        target_width = int(height * 9 / 16)
        if target_width > width:
            target_width = width
            target_height = int(target_width * 16 / 9)
        else:
            target_height = height
            
        logger.info(f"[Portrait] Resolution: {width}x{height} -> {target_width}x{target_height}")
            
        # 2. Analyze (Pass 1)
        analyzer = CameraPathAnalyzer(sensitivity, camera_smoothing, zoom_threshold, zoom_level)
        camera_path = analyzer.analyze(input_path, target_width, target_height)
        
        if not camera_path:
            raise Exception("Analysis failed to generate path")
            
        # 3. Render (Pass 2)
        logger.info(f"[Renderer] Starting Pass 2: Rendering {len(camera_path)} frames...")
        
        cap = cv2.VideoCapture(input_path)
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, fps, (target_width, target_height))
        
        frame_idx = 0
        while cap.isOpened() and frame_idx < len(camera_path):
            ret, frame = cap.read()
            if not ret:
                break
                
            config = camera_path[frame_idx]
            
            # Apply Zoom
            curr_zoom = config.zoom
            zoom_w = int(target_width / curr_zoom)
            zoom_h = int(target_height / curr_zoom)
            
            # Analyzer now calculates exact top-left corner (crop_x) for the zoomed box correctly centered
            x = config.crop_x
            y = (height - zoom_h) // 2
            
            # Bounds check
            x = max(0, min(x, width - zoom_w))
            y = max(0, min(y, height - zoom_h))
            
            # Crop
            crop = frame[y:y+zoom_h, x:x+zoom_w]
            
            # Resize
            if crop.shape[0] != target_height or crop.shape[1] != target_width:
                 crop = cv2.resize(crop, (target_width, target_height), interpolation=cv2.INTER_LANCZOS4)
            
            out.write(crop)
            
            if frame_idx % 200 == 0:
                logger.info(f"[Renderer] Rendered {frame_idx}/{total_frames}")
            frame_idx += 1
            
        cap.release()
        out.release()
        
        # 4. Add Audio & Re-encode for Compatibility
        logger.info("[FaceTrack] Muxing audio and re-encoding to H.264...")
        if os.path.exists(final_output): 
            try: os.remove(final_output)
            except: pass
        
        cmd = [
            'ffmpeg', '-y', '-loglevel', 'error', 
            '-i', output_path, '-i', input_path,
            '-map', '0:v:0', '-map', '1:a:0?',
            '-c:v', 'libx264', '-preset', 'slow', '-crf', '18',
            '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '192k', 
            '-movflags', '+faststart', '-shortest', 
            final_output
        ]
        subprocess.run(cmd, check=True)
        
        if os.path.exists(output_path):
            os.remove(output_path)
            
        logger.info(f"[FaceTrack] Complete: {final_output}")
        return final_output

    except Exception as e:
        logger.error(f"[FaceTrack] Error: {e}")
        logger.error(traceback.format_exc())
        return reframe_to_portrait(input_path, output_name)