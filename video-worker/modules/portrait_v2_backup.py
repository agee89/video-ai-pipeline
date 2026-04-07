import subprocess
import os
import json
import logging
import sys
import traceback
from dataclasses import dataclass
from typing import List, Optional, Dict, Tuple
from collections import deque
import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("portrait_pro")

@dataclass
class Face:
    """Representasi wajah yang terdeteksi"""
    x: int  # Center X
    y: int  # Center Y
    width: float
    height: float
    size: float  # Area wajah
    lip_activity: float
    confidence: float
    id: Optional[int] = None
    
    @property
    def area(self) -> float:
        return self.width * self.height
    
    @property
    def aspect_ratio(self) -> float:
        return self.width / self.height if self.height > 0 else 1.0

@dataclass
class CameraConfig:
    """Konfigurasi kamera per frame"""
    crop_x: int
    crop_y: int
    zoom: float
    is_cut: bool
    behavior_mode: str  # 'far', 'medium', 'close'
    target_face_id: Optional[int] = None
    debug_info: str = ""

class SpeakerIdentifier:
    """Identifikasi narasumber utama dalam podcast/interview"""
    
    def __init__(self):
        self.speaker_stats = {}  # face_id -> stats
        self.center_bias_weight = 4.0      # Posisi tengah sangat penting
        self.small_face_bonus = 2.0        # Bonus untuk wajah kecil (duduk belakang)
        self.speaking_weight = 5.0         # Aktivitas berbicara paling penting
        self.stability_weight = 1.5        # Konsistensi posisi
        
    def identify_main_speaker(self, faces: List[Face], frame_width: int, 
                            history_frames: int = 300) -> Optional[int]:
        """
        Identifikasi pembicara utama berdasarkan:
        - Posisi CENTER (paling penting)
        - Aktivitas berbicara (total waktu bicara)
        - Small face bonus (wajah kecil = duduk belakang = narasumber)
        - Stability (posisi konsisten)
        
        BUKAN berdasarkan ukuran wajah besar!
        """
        if not faces:
            return None
            
        center_x = frame_width / 2
        
        # Update stats untuk setiap wajah
        for face in faces:
            if face.id not in self.speaker_stats:
                self.speaker_stats[face.id] = {
                    'speaking_time': 0,
                    'center_score': 0,
                    'size_penalty': 0,      # Wajah besar = PENALTY
                    'stability_score': 0,
                    'frames_seen': 0,
                    'positions': []          # Track posisi untuk stability
                }
            
            stats = self.speaker_stats[face.id]
            stats['frames_seen'] += 1
            stats['positions'].append(face.x)
            
            # 1. CENTER SCORE: Semakin dekat ke tengah semakin tinggi
            distance_from_center = abs(face.x - center_x) / frame_width
            center_score = (1.0 - distance_from_center) ** 2  # Exponential untuk emphasis
            stats['center_score'] += center_score * self.center_bias_weight
            
            # 2. SMALL FACE BONUS: Wajah kecil (duduk belakang) dapat bonus
            # Normalisasi: size 0.05 = kecil, 0.30 = besar
            # Berikan bonus untuk wajah kecil-sedang (0.05 - 0.15)
            if face.size < 0.15:  # Wajah relatif kecil
                small_bonus = (0.15 - face.size) / 0.15  # 0 sampai 1
                stats['size_penalty'] += small_bonus * self.small_face_bonus
            elif face.size > 0.20:  # Wajah terlalu besar (terlalu dekat kamera)
                big_penalty = (face.size - 0.20) / 0.30
                stats['size_penalty'] -= big_penalty * 2.0  # PENALTY untuk wajah besar
            
            # 3. SPEAKING SCORE: Akumulasi aktivitas berbicara
            if face.lip_activity > 5.0:
                stats['speaking_time'] += face.lip_activity * self.speaking_weight
            
            # 4. STABILITY SCORE: Posisi konsisten = narasumber
            if len(stats['positions']) > 30:
                recent_positions = stats['positions'][-30:]
                position_variance = np.var(recent_positions)
                # Semakin stabil (variance kecil) semakin tinggi score
                stability = max(0, 1.0 - (position_variance / (frame_width * 0.1)))
                stats['stability_score'] += stability * self.stability_weight
        
        # Hitung total score
        best_id = None
        best_score = -999999
        
        for face_id, stats in self.speaker_stats.items():
            if stats['frames_seen'] < 20:  # Minimal visibility
                continue
            
            # Normalisasi per frame
            frames = stats['frames_seen']
            
            total_score = (
                stats['center_score'] / frames +           # Posisi tengah
                stats['size_penalty'] / frames +           # Bonus wajah kecil
                stats['speaking_time'] / frames +          # Aktivitas bicara
                stats['stability_score'] / frames          # Konsistensi posisi
            )
            
            if total_score > best_score:
                best_score = total_score
                best_id = face_id
        
        # Debug log
        if best_id is not None and len(self.speaker_stats) > 1:
            logger.info(f"[Speaker ID] Identified: ID {best_id} (score: {best_score:.2f})")
            for fid, stats in self.speaker_stats.items():
                frames = stats['frames_seen']
                if frames > 20:
                    score = (stats['center_score'] + stats['size_penalty'] + 
                            stats['speaking_time'] + stats['stability_score']) / frames
                    logger.info(f"  ID {fid}: score={score:.2f}, center={stats['center_score']/frames:.2f}, "
                              f"size_bonus={stats['size_penalty']/frames:.2f}, speaking={stats['speaking_time']/frames:.2f}")
                
        return best_id

class FaceTracker:
    """Tracking wajah dengan ID persistence - Enhanced untuk wajah kecil"""
    
    def __init__(self):
        self.next_id = 0
        self.active_faces = {}  # id -> Face
        self.lost_faces = {}  # id -> frames_lost
        self.max_lost_frames = 30  # Increased dari 15 untuk wajah kecil yang hilang sesaat
        self.match_threshold = 120  # Increased dari 80 untuk toleransi lebih besar pada wajah kecil
        self.face_size_history = {}  # id -> deque of sizes untuk detect size changes
        
    def update(self, detected_faces: List[Face]) -> List[Face]:
        """Update tracking dengan wajah yang terdeteksi - Enhanced untuk small faces"""
        matched_ids = set()
        result_faces = []
        
        # Match detected faces dengan tracked faces
        for face in detected_faces:
            best_match_id = None
            best_distance = float('inf')
            
            for tracked_id, tracked_face in self.active_faces.items():
                if tracked_id in matched_ids:
                    continue
                
                # Calculate distance dengan weight berdasarkan size
                # Wajah kecil diberi toleransi distance lebih besar
                size_factor = 1.0 + (0.15 - min(face.size, 0.15)) / 0.15  # 1.0 to 2.0
                adjusted_threshold = self.match_threshold * size_factor
                
                distance = np.sqrt(
                    (face.x - tracked_face.x)**2 + 
                    (face.y - tracked_face.y)**2
                )
                
                # Check size similarity dengan toleransi lebih besar untuk small faces
                size_diff = abs(face.size - tracked_face.size) / max(tracked_face.size, 0.01)
                max_size_diff = 0.8 if face.size < 0.12 else 0.5  # Toleransi lebih besar untuk wajah kecil
                
                if distance < adjusted_threshold and size_diff < max_size_diff:
                    if distance < best_distance:
                        best_distance = distance
                        best_match_id = tracked_id
            
            if best_match_id is not None:
                face.id = best_match_id
                matched_ids.add(best_match_id)
                self.active_faces[best_match_id] = face
                
                # Track size history
                if best_match_id not in self.face_size_history:
                    self.face_size_history[best_match_id] = deque(maxlen=10)
                self.face_size_history[best_match_id].append(face.size)
                
                if best_match_id in self.lost_faces:
                    del self.lost_faces[best_match_id]
            else:
                # Wajah baru
                face.id = self.next_id
                self.next_id += 1
                self.active_faces[face.id] = face
                self.face_size_history[face.id] = deque(maxlen=10)
                self.face_size_history[face.id].append(face.size)
                
            result_faces.append(face)
        
        # Update lost faces dengan grace period lebih panjang
        for tracked_id in list(self.active_faces.keys()):
            if tracked_id not in matched_ids:
                if tracked_id not in self.lost_faces:
                    self.lost_faces[tracked_id] = 0
                self.lost_faces[tracked_id] += 1
                
                # Grace period lebih panjang untuk wajah kecil (potentially far away)
                tracked_face = self.active_faces[tracked_id]
                max_lost = self.max_lost_frames
                if tracked_face.size < 0.12:  # Small face
                    max_lost = int(self.max_lost_frames * 1.5)  # 45 frames grace
                
                # Remove jika terlalu lama hilang
                if self.lost_faces[tracked_id] > max_lost:
                    del self.active_faces[tracked_id]
                    del self.lost_faces[tracked_id]
                    if tracked_id in self.face_size_history:
                        del self.face_size_history[tracked_id]
        
        return result_faces
    
    def reset(self):
        """Reset tracking (untuk scene cuts)"""
        self.active_faces.clear()
        self.lost_faces.clear()

class AdaptiveCameraController:
    """
    Kontrol kamera adaptif berdasarkan jarak subjek:
    - FAR (tripod): ULTRA STABLE - hampir tidak bergerak, seperti tripod profesional
    - MEDIUM: Smooth following, moderate responsiveness  
    - CLOSE: Free movement, follows head closely
    """
    
    def __init__(self):
        # Thresholds untuk behavior modes - REFINED untuk better tracking
        self.close_threshold = 0.25  # Wajah > 25% width = close (back to original)
        self.far_threshold = 0.15    # Wajah < 15% width = far
        # Range 15-25% = MEDIUM zone
        
        # Smoothing factors per mode - OPTIMIZED
        self.smoothing_factors = {
            'far': 0.0,       # ZERO - locked tripod (was 0.003)
            'medium': 0.15,   # Smooth balanced (was 0.08)
            'close': 0.40     # Very responsive untuk wajah besar (was 0.30)
        }
        
        # Zoom behavior per mode
        self.zoom_configs = {
            'far': {'enabled': False, 'level': 1.0},
            'medium': {'enabled': True, 'level': 1.08, 'threshold': 30.0},
            'close': {'enabled': True, 'level': 1.12, 'threshold': 25.0}
        }
        
        self.current_mode = 'medium'
        self.mode_history = deque(maxlen=90)  # REDUCED dari 120 untuk responsiveness
        
    def determine_behavior_mode(self, face: Face, frame_width: int) -> str:
        """Tentukan mode behavior berdasarkan ukuran wajah"""
        face_width_ratio = face.width / frame_width
        
        if face_width_ratio > self.close_threshold:
            return 'close'
        elif face_width_ratio < self.far_threshold:
            return 'far'
        else:
            return 'medium'
    
    def get_smoothing_factor(self, target_mode: str) -> float:
        """Dapatkan smoothing factor dengan stabilisasi mode - BALANCED"""
        self.mode_history.append(target_mode)
        
        # Untuk FAR mode, butuh konsensus kuat untuk stabilitas
        # Untuk CLOSE mode, lebih responsive
        if len(self.mode_history) >= 20:
            mode_counts = {}
            for mode in self.mode_history:
                mode_counts[mode] = mode_counts.get(mode, 0) + 1
            
            most_common_mode = max(mode_counts, key=mode_counts.get)
            
            # Hysteresis berbeda per mode
            if self.current_mode == 'far':
                # FAR mode: butuh 90% konsensus untuk keluar
                if mode_counts.get('far', 0) >= len(self.mode_history) * 0.10:
                    most_common_mode = 'far'
            elif self.current_mode == 'close':
                # CLOSE mode: butuh hanya 60% untuk stay (lebih responsive)
                if mode_counts.get('close', 0) >= len(self.mode_history) * 0.60:
                    most_common_mode = 'close'
            elif most_common_mode == 'far':
                # Masuk ke FAR: butuh 80% konsensus
                if mode_counts['far'] < len(self.mode_history) * 0.80:
                    most_common_mode = self.current_mode
            
            self.current_mode = most_common_mode
        else:
            self.current_mode = target_mode
            
        return self.smoothing_factors[self.current_mode]
    
    def should_zoom(self, face: Face, mode: str) -> Tuple[bool, float]:
        """Tentukan apakah harus zoom dan seberapa besar"""
        config = self.zoom_configs[mode]
        
        if not config['enabled']:
            return False, 1.0
            
        if face.lip_activity > config['threshold']:
            return True, config['level']
            
        return False, 1.0

class UltraSmoothAnalyzer:
    """
    Analyzer dengan tracking ultra smooth dan deteksi pembicara presisi tinggi
    ENHANCED: Deteksi wajah kecil di jarak jauh dengan stabilitas maksimal
    """
    
    def __init__(self, 
                 sensitivity: int = 5,
                 stability_threshold: float = 2.0):
        self.sensitivity = sensitivity
        self.stability_threshold = stability_threshold
        
        # Core components
        self.face_tracker = FaceTracker()
        self.speaker_id = SpeakerIdentifier()
        self.camera_controller = AdaptiveCameraController()
        
        # State
        self.main_speaker_id = None
        self.smooth_center_x = None
        self.smooth_center_y = None
        self.current_zoom = 1.0
        self.target_locked = False
        
        # FAR mode specific - LOCKED TRIPOD MODE
        self.far_mode_lock_frames = 0
        self.far_mode_min_lock = 300   # 10 detik @ 30fps - SANGAT LAMA
        self.far_mode_locked_position = None  # Lock posisi di FAR mode
        self.far_mode_active = False
        
        # Scene detection
        self.scene_threshold = 35.0
        
        # Detection interval - lebih sering untuk wajah kecil
        self.last_detection_frame = -1
        self.detection_interval_base = 3  # Detect setiap 3 frame
        
    def detect_scene_change(self, prev_frame, curr_frame) -> bool:
        """Deteksi scene cut dengan threshold yang lebih tinggi"""
        try:
            import cv2
            if prev_frame is None:
                return True
            
            # Histogram comparison untuk lebih akurat
            prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
            curr_gray = cv2.cvtColor(curr_frame, cv2.COLOR_BGR2GRAY)
            
            prev_hist = cv2.calcHist([prev_gray], [0], None, [256], [0, 256])
            curr_hist = cv2.calcHist([curr_gray], [0], None, [256], [0, 256])
            
            correlation = cv2.compareHist(prev_hist, curr_hist, cv2.HISTCMP_CORREL)
            
            return correlation < 0.6  # Threshold untuk scene cut
            
        except Exception as e:
            logger.warning(f"Scene detection error: {e}")
            return False
    
    def detect_faces(self, frame, face_detector, face_mesh, width: int, height: int) -> List[Face]:
        """Deteksi wajah dengan detail lengkap - ENHANCED untuk jarak jauh"""
        import cv2
        
        # Pre-process untuk deteksi wajah kecil yang lebih baik
        # Enhance contrast untuk wajah kecil di background
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        l = clahe.apply(l)
        enhanced = cv2.merge([l, a, b])
        rgb = cv2.cvtColor(enhanced, cv2.COLOR_LAB2RGB)
        
        faces = []
        
        # Detection dengan frame yang sudah di-enhance
        results = face_detector.process(rgb)
        if results.detections:
            for detection in results.detections:
                bbox = detection.location_data.relative_bounding_box
                
                # Filter false positives
                if bbox.width < 0.02 or bbox.height < 0.02:  # Terlalu kecil
                    continue
                if bbox.width > 0.8 or bbox.height > 0.8:    # Terlalu besar
                    continue
                
                face = Face(
                    x=int((bbox.xmin + bbox.width/2) * width),
                    y=int((bbox.ymin + bbox.height/2) * height),
                    width=bbox.width * width,
                    height=bbox.height * height,
                    size=bbox.width * bbox.height,
                    lip_activity=0,
                    confidence=detection.score[0] if detection.score else 0.5
                )
                faces.append(face)
        
        # Lip activity via face mesh (gunakan RGB original untuk akurasi)
        rgb_original = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mesh_results = face_mesh.process(rgb_original)
        if mesh_results.multi_face_landmarks:
            for landmarks in mesh_results.multi_face_landmarks:
                nose = landmarks.landmark[1]
                mesh_x = int(nose.x * width)
                mesh_y = int(nose.y * height)
                
                # Hitung lip opening lebih akurat
                upper_lip = landmarks.landmark[13].y
                lower_lip = landmarks.landmark[14].y
                lip_left = landmarks.landmark[61].x
                lip_right = landmarks.landmark[291].x
                
                vertical_open = abs(upper_lip - lower_lip) * height
                horizontal_width = abs(lip_right - lip_left) * width
                
                # Normalized lip activity
                lip_activity = vertical_open / max(horizontal_width * 0.5, 1.0)
                
                # Match ke face terdekat
                for face in faces:
                    dist = np.sqrt((face.x - mesh_x)**2 + (face.y - mesh_y)**2)
                    if dist < face.width:  # Within face bounds
                        face.lip_activity = max(face.lip_activity, lip_activity * 10)
        
        return faces
    
    def analyze(self, input_path: str, target_width: int, target_height: int) -> List[CameraConfig]:
        """Analisis video dengan tracking ultra presisi"""
        import cv2
        import mediapipe as mp
        
        logger.info("[Analyzer Pro] Starting ultra-precision analysis...")
        
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            raise Exception(f"Cannot open {input_path}")
        
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        # Setup detectors dengan konfigurasi optimal untuk SMALL FACES
        mp_face_detection = mp.solutions.face_detection
        face_detector = mp_face_detection.FaceDetection(
            model_selection=1,  # Model 1 = untuk jarak jauh (mendukung wajah kecil)
            min_detection_confidence=0.3  # TURUN dari 0.5 ke 0.3 untuk wajah kecil
        )
        
        mp_face_mesh = mp.solutions.face_mesh
        face_mesh = mp_face_mesh.FaceMesh(
            max_num_faces=5,
            min_detection_confidence=0.3,  # TURUN dari 0.5
            min_tracking_confidence=0.3    # TURUN dari 0.5
        )
        
        camera_path: List[CameraConfig] = []
        prev_frame = None
        frame_idx = 0
        
        # Initialize smooth position di center
        self.smooth_center_x = float(width / 2)
        self.smooth_center_y = float(height / 2)
        
        # Untuk identifikasi speaker, kumpulkan data dulu
        speaker_identification_frames = min(300, total_frames // 3)
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            is_cut = self.detect_scene_change(prev_frame, frame)
            
            if is_cut and frame_idx > 0:
                logger.info(f"[Analyzer Pro] Scene cut at frame {frame_idx}")
                self.face_tracker.reset()
                # JANGAN reset main_speaker_id - tetap ingat siapa main speaker
                # self.main_speaker_id = None  # REMOVED
                self.target_locked = False
                self.current_zoom = 1.0
                self.far_mode_lock_frames = 0
                self.far_mode_locked_position = None
                self.far_mode_active = False
                self.last_detection_frame = -1
            
            # Detect faces - FREQUENT detection untuk wajah kecil
            should_detect = (
                is_cut or 
                frame_idx - self.last_detection_frame >= self.detection_interval_base or
                frame_idx == 0
            )
            
            if should_detect:
                faces = self.detect_faces(frame, face_detector, face_mesh, width, height)
                self.last_detection_frame = frame_idx
            else:
                faces = []  # Will use tracked faces
            
            # Update tracking
            if faces:  # Only update if we have new detections
                tracked_faces = self.face_tracker.update(faces)
            else:
                # Use existing tracked faces
                tracked_faces = list(self.face_tracker.active_faces.values())
            
            # Identifikasi main speaker (HANYA SEKALI setelah collect cukup data)
            if frame_idx == speaker_identification_frames and not self.main_speaker_id:
                self.main_speaker_id = self.speaker_id.identify_main_speaker(
                    tracked_faces, width
                )
                if self.main_speaker_id is not None:
                    logger.info(f"[Analyzer Pro] Main speaker identified: ID {self.main_speaker_id}")
                else:
                    logger.warning(f"[Analyzer Pro] Could not identify main speaker after {speaker_identification_frames} frames")
            elif frame_idx < speaker_identification_frames:
                # Masih dalam fase identifikasi - collect data saja, jangan log
                self.speaker_id.identify_main_speaker(tracked_faces, width)
            
            # Pilih target face
            target_face = None
            
            if self.main_speaker_id is not None:
                # Prioritas ke main speaker
                target_face = next(
                    (f for f in tracked_faces if f.id == self.main_speaker_id), 
                    None
                )
            
            # Fallback: pilih yang paling aktif berbicara
            if target_face is None and tracked_faces:
                # Harus ada orang dalam frame
                active_faces = [f for f in tracked_faces if f.lip_activity > 3.0]
                
                if active_faces:
                    # Dari yang aktif bicara, pilih yang paling CENTER (bukan besar)
                    center_x = width / 2
                    target_face = min(
                        active_faces,
                        key=lambda f: abs(f.x - center_x) / width
                    )
                else:
                    # Tidak ada yang bicara, pilih yang paling CENTER dengan wajah KECIL-SEDANG
                    center_x = width / 2
                    
                    # Filter wajah yang tidak terlalu besar (< 20% frame)
                    suitable_faces = [f for f in tracked_faces if f.size < 0.20]
                    
                    if suitable_faces:
                        target_face = min(
                            suitable_faces,
                            key=lambda f: abs(f.x - center_x) / width
                        )
                    else:
                        # Semua wajah besar, ambil yang center saja
                        target_face = min(
                            tracked_faces,
                            key=lambda f: abs(f.x - center_x) / width
                        )
            
            # SELALU ada target (tidak pernah kosong)
            if target_face is None and tracked_faces:
                target_face = tracked_faces[0]
            
            # Determine camera behavior
            behavior_mode = 'medium'
            if target_face:
                behavior_mode = self.camera_controller.determine_behavior_mode(
                    target_face, width
                )
                
                # FAR MODE = LOCKED TRIPOD (NO MOVEMENT)
                if behavior_mode == 'far':
                    self.far_mode_lock_frames += 1
                    
                    # First time entering FAR mode - LOCK position
                    if not self.far_mode_active:
                        self.far_mode_locked_position = (float(target_face.x), float(target_face.y))
                        self.far_mode_active = True
                        logger.info(f"[FAR MODE] 🔒 LOCKED at position ({target_face.x}, {target_face.y})")
                else:
                    # MEDIUM/CLOSE MODE = ACTIVE TRACKING
                    # Keluar dari FAR mode harus memenuhi syarat strict
                    if self.far_mode_active:
                        # Butuh: 10 detik DAN wajah >20% untuk keluar
                        if self.far_mode_lock_frames >= self.far_mode_min_lock and target_face.size >= 0.20:
                            # OK untuk keluar dari FAR
                            self.far_mode_active = False
                            self.far_mode_locked_position = None
                            self.far_mode_lock_frames = 0
                            logger.info(f"[FAR MODE] 🔓 UNLOCKED - switching to {behavior_mode}")
                        else:
                            # Belum memenuhi syarat - STAY di FAR
                            behavior_mode = 'far'
                            self.far_mode_lock_frames += 1
                    else:
                        # Not in FAR mode - reset counter
                        self.far_mode_lock_frames = 0
            
            # Target position
            target_x = self.smooth_center_x
            target_y = self.smooth_center_y
            
            if target_face:
                target_x = float(target_face.x)
                target_y = float(target_face.y)
            
            # Smoothing berdasarkan behavior mode
            smoothing = self.camera_controller.get_smoothing_factor(behavior_mode)
            
            # FAR MODE: ZERO MOVEMENT (kecuali ada scene cut)
            if self.far_mode_active:
                if is_cut:
                    # Pada scene cut, update locked position
                    self.smooth_center_x = target_x
                    self.smooth_center_y = target_y
                    if target_face:
                        self.far_mode_locked_position = (target_x, target_y)
                # else: NO UPDATE - kamera tetap di posisi locked (smoothing = 0.0)
            else:
                # MEDIUM/CLOSE mode: ACTIVE SMOOTH TRACKING
                if is_cut:
                    self.smooth_center_x = target_x
                    self.smooth_center_y = target_y
                else:
                    # Exponential smoothing dengan factor yang sesuai mode
                    # CLOSE mode: 0.40 = sangat responsive untuk wajah besar
                    # MEDIUM mode: 0.15 = balanced smooth
                    self.smooth_center_x += smoothing * (target_x - self.smooth_center_x)
                    self.smooth_center_y += smoothing * (target_y - self.smooth_center_y)
            
            # Zoom logic - DISABLED di FAR mode
            zoom_target = 1.0
            
            if not self.far_mode_active:  # Only zoom in MEDIUM/CLOSE
                if target_face:
                    should_zoom, zoom_level = self.camera_controller.should_zoom(
                        target_face, behavior_mode
                    )
                    if should_zoom:
                        zoom_target = zoom_level
            # else: FAR mode = NO ZOOM (always 1.0)
            
            # Smooth zoom transition
            if is_cut:
                self.current_zoom = 1.0
            else:
                zoom_speed = 0.25 if zoom_target > self.current_zoom else 0.05
                self.current_zoom += zoom_speed * (zoom_target - self.current_zoom)
            
            # Calculate crop position
            visible_width = target_width / self.current_zoom
            visible_height = target_height / self.current_zoom
            
            crop_x = self.smooth_center_x - (visible_width / 2)
            crop_y = self.smooth_center_y - (visible_height / 2)
            
            # Bounds
            crop_x = max(0, min(crop_x, width - visible_width))
            crop_y = max(0, min(crop_y, height - visible_height))
            
            # Store config
            config = CameraConfig(
                crop_x=int(crop_x),
                crop_y=int(crop_y),
                zoom=self.current_zoom,
                is_cut=is_cut,
                behavior_mode=behavior_mode,
                target_face_id=target_face.id if target_face else None
            )
            camera_path.append(config)
            
            prev_frame = frame.copy()
            frame_idx += 1
            
            if frame_idx % 200 == 0:
                # Log dengan info wajah terdeteksi
                num_faces = len(tracked_faces)
                face_sizes = [f"{f.size:.3f}" for f in tracked_faces[:3]]  # Show first 3
                far_status = "🔒LOCKED" if self.far_mode_active else ""
                logger.info(f"[Analyzer Pro] Progress: {frame_idx}/{total_frames} | "
                          f"Mode: {behavior_mode} {far_status} | "
                          f"Faces: {num_faces} {face_sizes if face_sizes else ''} | "
                          f"Target: {target_face.id if target_face else 'None'} | "
                          f"Main: {self.main_speaker_id}")
        
        cap.release()
        face_detector.close()
        face_mesh.close()
        
        logger.info(f"[Analyzer Pro] Analysis complete: {len(camera_path)} frames")
        return camera_path

def reframe_portrait_ultra_smooth(
    input_path: str, 
    output_name: str,
    sensitivity: int = 5,
    stability_threshold: float = 2.0
) -> str:
    """
    Reframe video ke portrait dengan ultra smooth tracking
    """
    output_path = f"/app/output/{output_name}_temp.mp4"
    final_output = f"/app/output/{output_name}.mp4"
    
    try:
        import cv2
        import mediapipe as mp
    except ImportError as e:
        logger.error(f"Import error: {e}")
        raise
    
    try:
        # Get video info
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
        target_height = height
        
        if target_width > width:
            target_width = width
            target_height = int(target_width * 16 / 9)
        
        logger.info(f"[Portrait Pro] Input: {width}x{height} @ {fps}fps")
        logger.info(f"[Portrait Pro] Output: {target_width}x{target_height}")
        
        # PASS 1: Analyze
        analyzer = UltraSmoothAnalyzer(sensitivity, stability_threshold)
        camera_path = analyzer.analyze(input_path, target_width, target_height)
        
        if not camera_path:
            raise Exception("Analysis failed")
        
        # PASS 2: Render
        logger.info(f"[Renderer Pro] Rendering {len(camera_path)} frames...")
        
        cap = cv2.VideoCapture(input_path)
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, fps, (target_width, target_height))
        
        frame_idx = 0
        while cap.isOpened() and frame_idx < len(camera_path):
            ret, frame = cap.read()
            if not ret:
                break
            
            config = camera_path[frame_idx]
            
            # Apply zoom
            zoom_w = int(target_width / config.zoom)
            zoom_h = int(target_height / config.zoom)
            
            x = config.crop_x
            y = config.crop_y
            
            # Bounds check
            x = max(0, min(x, width - zoom_w))
            y = max(0, min(y, height - zoom_h))
            
            # Crop & resize
            crop = frame[y:y+zoom_h, x:x+zoom_w]
            
            if crop.shape[0] != target_height or crop.shape[1] != target_width:
                crop = cv2.resize(
                    crop, 
                    (target_width, target_height),
                    interpolation=cv2.INTER_LANCZOS4
                )
            
            out.write(crop)
            
            if frame_idx % 200 == 0:
                logger.info(f"[Renderer Pro] {frame_idx}/{total_frames}")
            
            frame_idx += 1
        
        cap.release()
        out.release()
        
        # Add audio & encode
        logger.info("[Portrait Pro] Final encoding...")
        
        if os.path.exists(final_output):
            try: 
                os.remove(final_output)
            except: 
                pass
        
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
        
        logger.info(f"[Portrait Pro] Complete: {final_output}")
        return final_output
        
    except Exception as e:
        logger.error(f"[Portrait Pro] Error: {e}")
        logger.error(traceback.format_exc())
        raise