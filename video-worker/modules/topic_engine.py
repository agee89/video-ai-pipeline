import subprocess
import json

def find_relevant_segments(transcript: list, topics: list) -> list:
    """
    Mencari segmen yang relevan berdasarkan topik (keyword matching)
    """
    segments = []
    current_segment = None
    
    for entry in transcript:
        text = entry['text'].lower()
        
        for topic in topics:
            if topic.lower() in text:
                if current_segment is None:
                    current_segment = {
                        'start': entry['start'],
                        'end': entry['start'] + entry['duration'],
                        'topic': topic,
                        'text': text
                    }
                else:
                    current_segment['end'] = entry['start'] + entry['duration']
                    current_segment['text'] += " " + text
                break
        else:
            if current_segment and (entry['start'] - current_segment['end']) > 10:
                segments.append(current_segment)
                current_segment = None
    
    if current_segment:
        segments.append(current_segment)
    
    return segments

def create_time_based_segments(video_path: str, segment_duration: int = 30, max_segments: int = 5) -> list:
    """
    Buat segments berdasarkan durasi waktu (fallback jika tidak ada transcript)
    
    Args:
        video_path: Path ke video file
        segment_duration: Durasi setiap segment dalam detik (default: 30)
        max_segments: Maksimal jumlah segments (default: 5)
    """
    try:
        # Get video duration using ffprobe
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'json',
            video_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        info = json.loads(result.stdout)
        total_duration = float(info['format']['duration'])
        
        segments = []
        current_time = 0
        segment_count = 0
        
        while current_time < total_duration and segment_count < max_segments:
            end_time = min(current_time + segment_duration, total_duration)
            
            segments.append({
                'start': current_time,
                'end': end_time,
                'topic': f'segment_{segment_count + 1}',
                'text': f'Time-based segment {segment_count + 1}'
            })
            
            current_time = end_time
            segment_count += 1
        
        return segments
        
    except Exception as e:
        # Fallback: buat 1 segment dari seluruh video (max 60 detik)
        return [{
            'start': 0,
            'end': 60,
            'topic': 'full_video',
            'text': 'Full video segment'
        }]