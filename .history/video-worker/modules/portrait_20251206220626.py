import cv2
import mediapipe as mp
import numpy as np

def reframe_to_portrait(input_path: str, output_name: str) -> str:
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
    
    while cap.isOpened():
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
    
    cap.release()
    out.release()
    face_detection.close()
    
    return output_path