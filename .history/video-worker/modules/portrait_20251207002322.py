import subprocess
import os
import json

def reframe_to_portrait(input_path: str, output_name: str) -> str:
    """
    Reframe video ke portrait (9:16) dengan FFmpeg - crop ke center
    """
    output_path = f"/app/output/{output_name}.mp4"
    
    try:
        # Get video dimensions
        probe_cmd = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            '-of', 'json',
            input_path
        ]
        
        result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
        info = json.loads(result.stdout)
        
        width = int(info['streams'][0]['width'])
        height = int(info['streams'][0]['height'])
        
        # Calculate target dimensions for 9:16 portrait
        target_width = int(height * 9 / 16)
        
        # If video is already narrow enough, just crop to 9:16
        if width <= target_width:
            target_width = width
        
        # Calculate crop position (center)
        crop_x = (width - target_width) // 2
        
        # FFmpeg command to crop video
        cmd = [
            'ffmpeg',
            '-i', input_path,
            '-vf', f'crop={target_width}:{height}:{crop_x}:0',
            '-c:a', 'copy',
            '-y',
            output_path
        ]
        
        subprocess.run(cmd, check=True, capture_output=True)
        
        return output_path
        
    except Exception as e:
        raise Exception(f"Portrait reframe failed: {str(e)}")


def reframe_to_portrait_with_face_tracking(input_path: str, output_name: str) -> str:
    """
    Reframe video ke portrait (9:16) dengan MediaPipe face tracking
    Ini lebih advanced tapi butuh lebih banyak resource
    """
    try:
        import cv2
        import mediapipe as mp
        import numpy as np
    except ImportError:
        # Fallback ke simple crop jika MediaPipe tidak tersedia
        return reframe_to_portrait(input_path, output_name)
    
    output_path = f"/app/output/{output_name}.mp4"
    
    mp_face = mp.solutions.face_detection
    face_detection = mp_face.FaceDetection(min_detection_confidence=0.5)
    
    cap = cv2.VideoCapture(input_path)
    fps = int(cap.get(cv2.CAP_PROP_FPS))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    target_width = int(height * 9 / 16)
    
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, fps, (target_width, height))
    
    frame_count = 0
    max_frames = fps * 60  # Limit to 60 seconds to avoid memory issues
    
    while cap.isOpened() and frame_count < max_frames:
        ret, frame = cap.read()
        if not ret:
            break
        
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = face_detection.process(rgb_frame)
        
        if results.detections:
            detection = results.detections[0]
            bbox = detection.location_data.relative_bounding_box
            face_center_x = int((bbox.xmin + bbox.width / 2) * width)
        else:
            face_center_x = width // 2
        
        crop_x = max(0, min(face_center_x - target_width // 2, width - target_width))
        cropped = frame[:, crop_x:crop_x + target_width]
        
        out.write(cropped)
        frame_count += 1
    
    cap.release()
    out.release()
    face_detection.close()
    
    return output_path