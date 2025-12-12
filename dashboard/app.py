import streamlit as st
import requests
import json
import time
import yt_dlp
import os
import re
import pkg_resources
from youtube_transcript_api import YouTubeTranscriptApi
from fontTools.ttLib import TTFont
import base64
import textwrap

# --- Config ---
WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL")


# --- Presets Logic ---
PRESETS_FILE = "caption_presets.json"

def get_default_settings():
    return {
        "cfg_font_family": "Komika Axis",
        "cfg_font_size": 60,
        "cfg_line_color": "#FFFFFF",
        "cfg_word_color": "#0FE631",
        "cfg_max_words": 2,
        "cfg_outline_width": 10,
        "cfg_outline_color": "#000000",
        "cfg_margin_v": 300,
        "cfg_position": "bottom_center",
        "cfg_bold": True,
        "cfg_italic": False,
        "cfg_all_caps": True
    }

def load_presets():
    if not os.path.exists(PRESETS_FILE):
        return {}
    try:
        with open(PRESETS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_preset(name, data):
    presets = load_presets()
    presets[name] = data
    with open(PRESETS_FILE, "w") as f:
        json.dump(presets, f, indent=2)

def delete_preset(name):
    presets = load_presets()
    if name in presets:
        del presets[name]
        with open(PRESETS_FILE, "w") as f:
            json.dump(presets, f, indent=2)

def apply_preset(preset_data):
    # Only update keys that exist in our settings
    defaults = get_default_settings()
    for k, v in preset_data.items():
        if k in defaults:
            st.session_state[k] = v

# Initialize Session State with Defaults if new
if "cfg_font_family" not in st.session_state:
    for k, v in get_default_settings().items():
        st.session_state[k] = v

# Load immediately


st.set_page_config(
    page_title="AI Clipper Generator",
    page_icon="🤖",
    layout="centered", # Single column centered
    initial_sidebar_state="collapsed"
)

# --- Custom CSS (Original Simple Style) ---
st.markdown("""
<style>
    .stButton>button {
        width: 100%;
        background-color: #FF4B4B;
        color: white;
        font-weight: bold;
        padding-top: 5px;
        padding-bottom: 5px;
    }
    .stTextInput>div>div>input {
        background-color: #f0f2f6;
    }
    .main-header {
        text-align: center;
        margin-bottom: 2rem;
    }
    .block-container {
        padding-top: 1rem;
    }
</style>
""", unsafe_allow_html=True)

# --- Header ---
st.markdown("<h1 class='main-header'>🤖 AI Video Clipper</h1>", unsafe_allow_html=True)
st.caption("Generate viral short clips from YouTube with auto-transcription and face tracking.")

if not WEBHOOK_URL:
    st.error("⚠️ Configuration Error: N8N_WEBHOOK_URL environment variable is missing!")

# --- Session State ---
if 'meta_data' not in st.session_state:
    st.session_state['meta_data'] = None
if 'transcript_text' not in st.session_state:
    st.session_state['transcript_text'] = ""

# --- Helper Functions ---
def get_video_info(url):
    ydl_opts = {'quiet': True, 'no_warnings': True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            return ydl.extract_info(url, download=False)
        except Exception:
            return None

def format_transcript(transcript_data):
    formatted_text = []
    seen_lines = set()
    
    if not transcript_data:
        return ""
        
    for item in transcript_data:
        # Handle dict vs object
        if isinstance(item, dict):
             start = float(item.get('start', 0))
             text = item.get('text', '')
        else:
             start = float(getattr(item, 'start', 0))
             text = getattr(item, 'text', '')

        minutes = int(start // 60)
        seconds = int(start % 60)
        text = text.replace('\n', ' ').strip()
        
        if not text: continue
        
        timestamped_line = f"[{minutes:02d}:{seconds:02d}] {text}"
        
        if timestamped_line not in seen_lines:
            formatted_text.append(timestamped_line)
            seen_lines.add(timestamped_line)
            
    return "\n".join(formatted_text)

def fetch_transcript(url):
    print(f"DEBUG: Fetching transcript for {url}", flush=True)
    try:
        # Extract Video ID
        video_id_match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11}).*', url)
        if not video_id_match:
            return None, "Invalid YouTube URL"
        video_id = video_id_match.group(1)
        
        # --- METHOD 1: youtube-transcript-api ---
        try:
            if hasattr(YouTubeTranscriptApi, 'list_transcripts'):
                transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
                transcript = None
                try:
                    transcript = transcript_list.find_transcript(['id'])
                except:
                    try:
                        transcript = transcript_list.find_generated_transcript(['id'])
                    except:
                        for t in transcript_list:
                            transcript = t
                            break
                
                if transcript:
                    transcript_data = transcript.fetch()
                    return format_transcript(transcript_data), None

            elif hasattr(YouTubeTranscriptApi, 'list'):
                # New/Alternative API v1.x
                print(f"DEBUG: Using v1.x API (.list)", flush=True)
                api = YouTubeTranscriptApi()
                transcript_list = api.list(video_id)
                
                # Check if it has find_transcript (likely specific to this version)
                # Or if list() returns data directly? 
                # Based on Step 1374, it tried to use find_transcript on the result of list()
                
                transcript = None
                # Try find pattern
                if hasattr(transcript_list, 'find_transcript'):
                     try: transcript = transcript_list.find_transcript(['id'])
                     except: pass
                
                # Manual iterate if find failed or not present
                if not transcript:
                    # Iterate to find 'id' or take first
                    try:
                        for t in transcript_list:
                            if t.language_code == 'id':
                                transcript = t
                                break
                        if not transcript:
                            # Take first available
                            try:
                                transcript = next(iter(transcript_list))
                            except: pass
                    except: pass

                if transcript:
                     transcript_data = transcript.fetch()
                     return format_transcript(transcript_data), None
                
                # Fallback: direct fetch if .list didn't yield transcript obj
                if hasattr(api, 'fetch'):
                     transcript_data = api.fetch(video_id)
                     return format_transcript(transcript_data), None

        except Exception as e:
            print(f"WARNING: Method 1 failed: {e}", flush=True)

        # --- METHOD 2: yt-dlp (Fallback) ---
        print(f"DEBUG: [Method 2] Attempting yt-dlp for {url}", flush=True)
        try:
            ydl_opts = {
                'skip_download': True,
                'writeautomaticsub': True,
                'writesub': True,
                'sublangs': ['id', 'en', '.*'],
                'quiet': True,
                'no_warnings': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                subs = info.get('requested_subtitles') or info.get('subtitles') or info.get('automatic_captions')
                
                if subs:
                    sub_url = None
                    for lang in ['id', 'id-orig', 'en', 'en-orig']:
                         if lang in subs:
                             sub_data = subs[lang]
                             sub_url = sub_data[0]['url'] if isinstance(sub_data, list) else sub_data['url']
                             break
                    
                    if not sub_url and subs:
                        first_key = list(subs.keys())[0]
                        sub_data = subs[first_key]
                        sub_url = sub_data[0]['url'] if isinstance(sub_data, list) else sub_data['url']
                             
                    if sub_url:
                             try:
                                 r = requests.get(sub_url)
                                 if r.status_code == 200:
                                     transcript_data = []
                                     try:
                                         data = r.json()
                                         events = data.get('events', [])
                                         for event in events:
                                             if 'segs' in event and 'tStartMs' in event:
                                                 text = "".join([s['utf8'] for s in event['segs'] if 'utf8' in s])
                                                 if text.strip():
                                                     transcript_data.append({
                                                         'start': event['tStartMs'] / 1000.0,
                                                         'text': text.strip()
                                                     })
                                     except:
                                         content = r.text
                                         lines = content.splitlines()
                                         current_start = None
                                         time_pattern = re.compile(r'(\d{2}:)?(\d{2}):(\d{2})\.(\d{3})\s-->\s.*')
                                         for line in lines:
                                             line = line.strip()
                                             if not line: continue
                                             match = time_pattern.match(line)
                                             if match:
                                                 h = int(match.group(1).replace(':', '')) if match.group(1) else 0
                                                 m, s, ms = int(match.group(2)), int(match.group(3)), int(match.group(4))
                                                 current_start = h * 3600 + m * 60 + s + ms / 1000.0
                                             elif current_start is not None and not line.isdigit() and '-->' not in line:
                                                 clean_text = re.sub(r'<[^>]+>', '', line).strip()
                                                 if clean_text:
                                                     transcript_data.append({'start': current_start, 'text': clean_text})
                                                 current_start = None

                                     if transcript_data:
                                          return format_transcript(transcript_data), None
                             except:
                                 pass
        except Exception as e:
             print(f"WARNING: Method 2 failed: {e}", flush=True)
            
        return None, "Could not fetch transcript from any source (YouTube API blocked?)"

    except Exception as e:
        return None, str(e)

# --- INPUT SECTION ---
with st.container():
    st.subheader("1. Source Video")
    col_input, col_btn = st.columns([4, 1]) # Original columns, no vertical_alignment arg in old Streamlit versions if needed, but keeping simple
    
    with col_input:
        youtube_url = st.text_input("YouTube Link", placeholder="https://youtube.com/watch?v=...")
    
    with col_btn:
        st.write("") # Spacer
        st.write("") 
        load_btn = st.button("Load Data", type="primary")

    if load_btn and not youtube_url:
        st.warning("⚠️ Mohon masukkan Link YouTube terlebih dahulu!")

    if load_btn and youtube_url:
        with st.spinner("Fetching Metadata & Transcript..."):
            info = get_video_info(youtube_url)
            if info:
                channel_name = info.get('channel') or info.get('uploader') or "Unknown Channel"
                st.session_state['meta_data'] = {
                    "title": info.get('title'),
                    "channel": channel_name,
                    "thumbnail": info.get('thumbnail')
                }
                
                transcript_text, error_msg = fetch_transcript(youtube_url)
                if transcript_text:
                    st.session_state['transcript_text'] = transcript_text
                    st.success(f"Transcript loaded! ({len(transcript_text.splitlines())} lines)")
                else:
                    st.session_state['transcript_text'] = ""
                    st.warning(f"Metadata loaded, but transcript failed: {error_msg}")
            else:
                st.error("Failed to load video info.")

# --- PREVIEW & DETAILS ---
if st.session_state['meta_data']:
    meta = st.session_state['meta_data']
    
    with st.container():
        col_thumb, col_details = st.columns([1, 2])
        
        with col_thumb:
            st.image(meta['thumbnail'], use_container_width=True)
            
        with col_details:
            st.subheader(meta['title'])
            channel_name = st.text_input("Channel Name", value=meta['channel'])
            
    st.subheader("2. Context")
    transcript = st.text_area("Video Transcript", value=st.session_state['transcript_text'], height=250)

    st.markdown("---")
    st.subheader("3. Configuration")
    
    with st.expander("⚙️ Advanced Camera Settings", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Face Tracking**")
            sensitivity = st.slider("Sensitivity", 1, 10, 5, help="Higher = Faster switching")
            zoom_threshold = st.slider("Zoom Threshold", 5.0, 30.0, 20.0, help="Lower = Easier zoom")
            
        with col2:
            st.markdown("**Camera Motion**")
            smoothing = st.slider("Smoothing", 0.05, 0.5, 0.25, help="Higher = Faster movement")
            zoom_level = st.slider("Zoom Amount", 1.0, 1.5, 1.15, help="1.15 = 15% Zoom")

    # --- 4. CAPTION SETTINGS & PREVIEW ---
    st.markdown("---")
    st.subheader("4. Caption Analysis & Styling")
    
    col_cap_settings, col_cap_preview = st.columns([1, 1])
    
    with col_cap_settings:
        st.write("**Style Configuration**")
        
        # --- PRESET MANAGEMENT ---
        with st.expander("💾 Load / Save Preset", expanded=True):
            presets = load_presets()
            preset_names = ["-- Select Preset --"] + list(presets.keys())
            
            # Load
            c_load1, c_load2 = st.columns([3, 1])
            with c_load1:
                selected_preset = st.selectbox("Load Preset", preset_names, label_visibility="collapsed")
            with c_load2:
                if st.button("Load"):
                    if selected_preset and selected_preset != "-- Select Preset --":
                        apply_preset(presets[selected_preset])
                        st.rerun()
            
            # Save
            c_save1, c_save2 = st.columns([3, 1])
            with c_save1:
                new_preset_name = st.text_input("New Preset Name", placeholder="My Custom Style")
            with c_save2:
                if st.button("Save"):
                    if new_preset_name:
                        # Gather current settings
                        current_data = {k: st.session_state[k] for k in get_default_settings().keys() if k in st.session_state}
                        save_preset(new_preset_name, current_data)
                        st.success(f"Saved!")
                        time.sleep(1)
                        st.rerun()

            # Delete
            if selected_preset and selected_preset != "-- Select Preset --":
                if "confirm_delete" not in st.session_state:
                    st.session_state.confirm_delete = None

                if st.session_state.confirm_delete != selected_preset:
                    if st.button("Delete Preset", type="secondary"):
                        st.session_state.confirm_delete = selected_preset
                        st.rerun()
                else:
                    st.warning(f"⚠️ Delete '{selected_preset}'?")
                    col_conf1, col_conf2 = st.columns(2)
                    with col_conf1:
                        if st.button("✅ Yes, Delete", type="primary"):
                            delete_preset(selected_preset)
                            st.session_state.confirm_delete = None
                            st.rerun()
                    with col_conf2:
                        if st.button("❌ Cancel"):
                            st.session_state.confirm_delete = None
                            st.rerun()
            
        st.markdown("---")
        
        # Font Settings
        def get_available_fonts_map():
            font_dir = "/app/fonts"
            defaults = {"Komika Axis": "KOMIKAX_.ttf", "Montserrat": "Montserrat-Regular.ttf", "Arial": "arial.ttf", "Impact": "impact.ttf"} 
            font_map = {} 
            try:
                if os.path.exists(font_dir):
                    for filename in os.listdir(font_dir):
                        if not filename.lower().endswith(('.ttf', '.otf')):
                            continue
                        filepath = os.path.join(font_dir, filename)
                        try:
                            font = TTFont(filepath)
                            family_name = ""
                            for record in font['name'].names:
                                if record.nameID == 1: 
                                    family_name = record.string.decode(record.getEncoding())
                                    break
                            if not family_name:
                                for record in font['name'].names:
                                    if record.nameID == 4: 
                                        family_name = record.string.decode(record.getEncoding())
                                        break
                            display_name = family_name.replace('\x00', '') if family_name else os.path.splitext(filename)[0]
                            font_map[display_name] = filename
                        except Exception:
                            font_map[os.path.splitext(filename)[0]] = filename
                            pass
            except Exception as e:
                pass
            if font_map:
                return dict(sorted(font_map.items()))
            return defaults

        font_map = get_available_fonts_map()
        available_font_names = list(font_map.keys())

        # Ensure loaded font is in list, otherwise default to first
        default_font_idx = 0
        current_font = st.session_state.get("cfg_font_family", "Komika Axis")
        if current_font in available_font_names:
            default_font_idx = available_font_names.index(current_font)

        c1, c2 = st.columns(2)
        with c1:
            font_family = st.selectbox("Font Family", available_font_names, index=default_font_idx, key="cfg_font_family")
            font_size = st.number_input("Font Size (px)", 40, 200, step=10, key="cfg_font_size")
        with c2:
            line_color = st.color_picker("Text Color", key="cfg_line_color")
            word_color = st.color_picker("Highlight Color", key="cfg_word_color")
            
        # Layout Settings
        
        # Ensure position index
        pos_opts = ["bottom_center", "bottom_left", "bottom_right", "top_center", "top_left", "top_right", "center"]
        curr_pos = st.session_state.get("cfg_position", "bottom_center")
        pos_idx = pos_opts.index(curr_pos) if curr_pos in pos_opts else 0

        c3, c4 = st.columns(2)
        with c3:
            max_words = st.number_input("Max Words/Line", 1, 10, key="cfg_max_words")
            outline_width = st.number_input("Outline Width", 0, 20, key="cfg_outline_width")
        with c4:
            margin_v = st.number_input("Vertical Margin (px)", 0, 1000, help="Distance from vertical edge", key="cfg_margin_v")
            position = st.selectbox("Position", pos_opts, index=pos_idx, key="cfg_position")

        # Toggles
        c5, c6 = st.columns(2)
        with c5:
            is_bold = st.checkbox("Bold Text", key="cfg_bold")
            is_italic = st.checkbox("Italic Text", key="cfg_italic")
        with c6:
            is_all_caps = st.checkbox("All Caps", key="cfg_all_caps")
            outline_color = st.color_picker("Outline Color", key="cfg_outline_color")

    with col_cap_preview:
        st.write("**Live Preview (Approximate)**")
        
        # --- Preview Calculation Logic ---
        
        # 1. Load and Embed Font
        font_base64 = ""
        font_mime = "font/ttf"
        selected_filename = font_map.get(font_family)
        
        if selected_filename:
             try:
                 file_path = os.path.join("/app/fonts", selected_filename)
                 if os.path.exists(file_path):
                     with open(file_path, "rb") as f:
                         font_bytes = f.read()
                         font_base64 = base64.b64encode(font_bytes).decode()
                         if selected_filename.lower().endswith(".otf"):
                             font_mime = "font/otf"
             except Exception as e:
                 print(f"Error embedding font: {e}")

        # Generate CSS @font-face block if we have the file
        custom_font_css = ""
        if font_base64:
            # Use a unique sanitized name for the CSS font-family to avoid conflicts
            # e.g. "Komika Axis" -> "KomikaAxis"
            safe_family = ''.join(c for c in font_family if c.isalnum())
            
            # print(f"DEBUG: Embedding font {font_family} ({len(font_base64)} bytes) as '{safe_family}'", flush=True)
            custom_font_css = textwrap.dedent(f"""
                <style>
                @font-face {{
                    font-family: '{safe_family}';
                    src: url(data:{font_mime};base64,{font_base64}) format('{ "opentype" if "otf" in font_mime else "truetype" }');
                    font-weight: normal;
                    font-style: normal;
                    font-display: block; 
                }}
                </style>
            """)
            preview_font_family = safe_family
        else:
             # print(f"DEBUG: No base64 data for {font_family}", flush=True)
             pass
        
        # 1. Scale Factors (Preview is roughly 1/4 the size of 1080p vertical video)
        # Using 300px height for preview box vs 1920px real video -> ~0.15 scale
        SCALE = 0.25 
        
        # 2. Font Size
        preview_font_size = int(font_size * SCALE)
        
        # 3. Margins
        scaled_margin = int(margin_v * SCALE)
        
        # 4. Outline - USE TEXT STROKE INSTEAD OF SHADOW
        # CSS text-stroke is centered. To mimic ASS "Outline" (which is outside), 
        # we need double the width because half is hidden behind the fill (due to paint-order).
        scaled_outline = max(0, outline_width * SCALE * 2) 
        
        # CSS for outline: Standard text-stroke (modern browsers) + Fallback text-shadow
        # text-stroke is much closer to video render than text-shadow
        outline_css = ""
        if scaled_outline > 0:
             # Using flex/bold thickness for stroke color
             outline_css = f"-webkit-text-stroke: {scaled_outline}px {outline_color}; paint-order: stroke fill;"

        # 5. Position Logic
        css_justify = "center"     
        css_align_items = "flex-end" 
        css_text_align = "center"
        
        style_margin_top = "0"
        style_margin_bottom = "0"

        # Vertical
        if "top" in position:
            css_align_items = "flex-start"
            style_margin_top = f"{scaled_margin}px"
        elif "center" == position:
            css_align_items = "center"
        elif "bottom" in position:
             css_align_items = "flex-end"
             style_margin_bottom = f"{scaled_margin}px"

        # Horizontal
        if "left" in position:
            css_justify = "flex-start"
            css_text_align = "left"
        elif "right" in position:
            css_justify = "flex-end"
            css_text_align = "right"
        else:
            css_justify = "center"
            css_text_align = "center"

        # 6. Text Processing
        raw_text = "Sample Caption Text Preview"
        if is_all_caps:
            raw_text = raw_text.upper()
            
        words = raw_text.split()
        preview_html = ""
        for i, w in enumerate(words):
            if i > 0 and i % max_words == 0:
                preview_html += "<br>"
            elif i > 0:
                preview_html += " "
            
            # Highlight Logic
            if i == 1: 
                preview_html += f'<span style="color: {word_color};">{w}</span>'
            else:
                preview_html += f'<span style="color: {line_color};">{w}</span>'

        css_weight = "bold" if is_bold else "normal"
        css_style = "italic" if is_italic else "normal"
        
        # Render CSS separately
        if custom_font_css:
            st.markdown(custom_font_css, unsafe_allow_html=True)
            
        # Render Preview HTML
        st.markdown(f"""
<div style="position: relative; width: 100%; aspect-ratio: 9/16; background-image: url('{meta['thumbnail']}'); background-size: cover; background-position: center; border-radius: 8px; overflow: hidden; display: flex; flex-direction: column; justify-content: {css_align_items}; align-items: {css_justify}; border: 2px solid #ddd;">
<div style="margin-top: {style_margin_top}; margin-bottom: {style_margin_bottom}; padding: 10px; text-align: {css_text_align}; width: 100%;">
<p style="font-family: '{preview_font_family}', sans-serif; font-size: {preview_font_size}px; font-weight: {css_weight}; font-style: {css_style}; margin: 0; line-height: 1.2; {outline_css}">
{preview_html}
</p>
<p style="font-size: 10px; color: rgba(255,255,255,0.7); margin-top: 5px; text-shadow: 1px 1px 2px black;">(Pos: {position}, Margin: {margin_v}px)</p>
</div>
</div>
""", unsafe_allow_html=True)

    st.write("")
    if st.button("🚀 GENERATE CLIPPER (Webhook)", type="primary"):
        # Construct Payload
        payload = {
            "youtube_url": youtube_url,
            "channel_name": channel_name,
            "transcript": transcript,
            "parameters": {
                "portrait": True,
                "face_tracking": True,
                "tracking_sensitivity": sensitivity,
                "camera_smoothing": smoothing,
                "zoom_threshold": zoom_threshold,
                "zoom_level": zoom_level,
            },
            "caption_conf": {
                "model": "small",
                "language": "id",
                "settings": {
                    "font_family": font_family,
                    "font_size": font_size,
                    "line_color": line_color,
                    "word_color": word_color,
                    "all_caps": is_all_caps,
                    "max_words_per_line": max_words,
                    "bold": is_bold,
                    "italic": is_italic,
                    "outline_width": outline_width,
                    "outline_color": outline_color,
                    "margin_v": margin_v,
                    "position": position
                }
            }
        }
        
        with st.spinner("Dispatching to Automa..."):
            try:
                r = requests.post(WEBHOOK_URL, json=payload)
                if r.status_code == 200:
                    st.success("✅ Job Submitted Successfully to Your Workflow!")
                    st.json(r.json() if r.content else {"status": "ok"})
                else:
                    st.error(f"❌ Webhook Error: {r.status_code}")
                    st.write(r.text)
            except Exception as e:
                st.error(f"Connection Failed: {e}")
