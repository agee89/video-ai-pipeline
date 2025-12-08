import subprocess
import os
import json

def reframe_to_portrait(input_path: str, output_name: str) -> str:
    """
    Reframe video ke portrait 9:16 dengan kualitas tinggi
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
        
        original_width = int(info['streams'][0]['width'])
        original_height = int(info['streams'][0]['height'])
        
        print(f"Original dimensions: {original_width}x{original_height}")
        
        # Target portrait dimensions (9:16 ratio)
        # Kita set tinggi tetap, lebar disesuaikan dengan ratio 9:16
        target_height = original_height
        target_width = int(target_height * 9 / 16)
        
        # Jika original width lebih kecil dari target, adjust
        if original_width < target_width:
            target_width = original_width
            target_height = int(target_width * 16 / 9)
        
        # Calculate crop position (center)
        crop_x = (original_width - target_width) // 2
        crop_y = 0
        
        print(f"Target dimensions: {target_width}x{target_height} (9:16)")
        print(f"Crop position: x={crop_x}, y={crop_y}")
        
        # FFmpeg command dengan crop dan scale untuk portrait
        cmd = [
            'ffmpeg',
            '-i', input_path,
            '-vf', f'crop={target_width}:{target_height}:{crop_x}:{crop_y},scale=1080:1920:flags=lanczos',
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-crf', '23',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-movflags', '+faststart',
            '-y',
            output_path
        ]
        
        print(f"Running FFmpeg command...")
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        
        # Verify output dimensions
        verify_cmd = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            '-of', 'csv=p=0',
            output_path
        ]
        
        verify_result = subprocess.run(verify_cmd, capture_output=True, text=True, check=True)
        final_dims = verify_result.stdout.strip()
        print(f"Final dimensions: {final_dims}")
        
        return output_path
        
    except Exception as e:
        print(f"Portrait reframe error: {str(e)}")
        raise Exception(f"Portrait reframe failed: {str(e)}")


def reframe_to_portrait_with_face_tracking(input_path: str, output_name: str) -> str:
    """
    Portrait mode dengan face tracking menggunakan MediaPipe
    """
    try:
        import cv2
        import mediapipe as mp
        import numpy as np
    except ImportError:
        print("MediaPipe not available, using simple crop")
        return reframe_to_portrait(input_path, output_name)
    
    output_path = f"/app/output/{output_name}_temp.mp4"
    final_output = f"/app/output/{output_name}.mp4"
    
    try:
        mp_face = mp.solutions.face_detection
        face_detection = mp_face.FaceDetection(min_detection_confidence=0.5)
        
        cap = cv2.VideoCapture(input_path)
        fps = int(cap.get(cv2.CAP_PROP_FPS))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        # Target 9:16 portrait
        target_width = int(height * 9 / 16)
        if target_width > width:
            target_width = width
            target_height = int(target_width * 16 / 9)
        else:
            target_height = height
        
        print(f"Face tracking: {width}x{height} -> {target_width}x{target_height}")
        
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, fps, (target_width, target_height))
        
        frame_count = 0
        max_frames = fps * 120  # Max 2 minutes
        
        while cap.isOpened() and frame_count < max_frames:
            ret, frame = cap.read()
            if not ret:
                break
            
            # Detect face
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = face_detection.process(rgb_frame)
            
            if results.detections:
                detection = results.detections[0]
                bbox = detection.location_data.relative_bounding_box
                face_center_x = int((bbox.xmin + bbox.width / 2) * width)
            else:
                face_center_x = width // 2
            
            # Crop with smooth transition
            crop_x = max(0, min(face_center_x - target_width // 2, width - target_width))
            crop_y = max(0, min(0, height - target_height))
            
            cropped = frame[crop_y:crop_y + target_height, crop_x:crop_x + target_width]
            
            if cropped.shape[0] != target_height or cropped.shape[1] != target_width:
                cropped = cv2.resize(cropped, (target_width, target_height))
            
            out.write(cropped)
            frame_count += 1
            
            if frame_count % 100 == 0:
                print(f"Processed {frame_count} frames...")
        
        cap.release()
        out.release()
        face_detection.close()
        
        print("Re-encoding with proper codec...")
        
        # Re-encode dengan codec yang proper
        cmd = [
            'ffmpeg',
            '-i', output_path,
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-crf', '23',
            '-vf', 'scale=1080:1920:flags=lanczos',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-movflags', '+faststart',
            '-y',
            final_output
        ]
        
        subprocess.run(cmd, check=True, capture_output=True)
        
        # Cleanup temp file
        if os.path.exists(output_path):
            os.remove(output_path)
        
        return final_output
        
    except Exception as e:
        print(f"Face tracking failed: {e}, falling back to simple crop")
        return reframe_to_portrait(input_path, output_name)