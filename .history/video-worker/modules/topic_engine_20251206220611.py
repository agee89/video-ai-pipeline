def find_relevant_segments(transcript: list, topics: list) -> list:
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