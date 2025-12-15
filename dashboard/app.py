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
THUMB_PRESETS_FILE = "thumbnail_presets.json"

def get_default_settings():
    return {
        "cfg_font_family": "Komika Axis",
        "cfg_font_size": 130,
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

# --- Thumbnail Presets Logic ---
def get_thumb_default_settings():
    return {
        "thumb_font": "Komika Axis",
        "thumb_size": 100,
        "thumb_weight": "bold",
        "thumb_color": "#FFFFFF",
        "thumb_transform": "capitalize",
        "thumb_stroke_color": "#333333",
        "thumb_stroke_width": 2,
        "thumb_shadow_color": "#904F26",
        "thumb_spacing": 1,
        "thumb_line_height": 1.2,
        "thumb_bg_enable": True,
        "thumb_bg_full": True,
        "thumb_bg_gradient": True,
        "thumb_bg_color": "rgba(255, 170, 0, 1.9)",
        "thumb_grad_height": 1000,
        "thumb_pos_y": "bottom",
        "thumb_margin_btm": 150,
        "thumb_edge_pad": 10,
        "thumb_max_lines": 4
    }

def load_thumb_presets():
    if not os.path.exists(THUMB_PRESETS_FILE):
        return {}
    try:
        with open(THUMB_PRESETS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_thumb_preset(name):
    # Capture current settings based on defaults
    data = {}
    defaults = get_thumb_default_settings()
    for k in defaults.keys():
        if k in st.session_state:
            data[k] = st.session_state[k]
    
    presets = load_thumb_presets()
    presets[name] = data
    with open(THUMB_PRESETS_FILE, "w") as f:
        json.dump(presets, f, indent=2)

def delete_thumb_preset(name):
    presets = load_thumb_presets()
    if name in presets:
        del presets[name]
        with open(THUMB_PRESETS_FILE, "w") as f:
            json.dump(presets, f, indent=2)

def apply_thumb_preset(preset_name):
    presets = load_thumb_presets()
    if preset_name in presets:
        data = presets[preset_name]
        for k, v in data.items():
            st.session_state[k] = v

# Initialize Session State with Defaults if new
if "cfg_font_family" not in st.session_state:
    for k, v in get_default_settings().items():
        st.session_state[k] = v

# Ensure Thumbnail defaults are also initialized (Fix for partial preset saving)
if "thumb_font" not in st.session_state:
    for k, v in get_thumb_default_settings().items():
        st.session_state[k] = v

# Load immediately


st.set_page_config(
    page_title="AI Video Clipper",
    page_icon="🎬",
    layout="centered",
    initial_sidebar_state="expanded"
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
        margin-bottom: 1rem;
    }
    .block-container {
        padding-top: 1rem;
        max-width: 790px; /* Constrain width for proportionality */
        margin: auto;
    }
</style>
""", unsafe_allow_html=True)

# --- Header ---
st.markdown("<h1 class='main-header'>🤖 AI Video Clipper</h1>", unsafe_allow_html=True)

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
    col_input, col_btn = st.columns([4, 1], vertical_alignment="bottom") 
    
    with col_input:
        youtube_url = st.text_input("", placeholder="Youtube URL Here (eg: https://youtube.com/watch?v=...", key="clipper_url")
    
    with col_btn:
        load_btn = st.button("Load Data", type="primary", use_container_width=True, key="clipper_load")

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
                    "thumbnail": info.get('thumbnail'),
                    "video_url": youtube_url # Store for thumbnail reuse
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
            channel_name = st.text_input("Channel Name", value=meta['channel'], key="clipper_channel")
            
    # Transcript Section (Hidden by default)
    if st.session_state.get('transcript_text'):
        with st.expander("👁️ Show/Edit Transcript"):
            transcript = st.text_area("Video Transcript", value=st.session_state['transcript_text'], height=250, key="clipper_transcript")
    else:
        # Fallback if empty
        transcript = st.text_area("Video Transcript", value="", height=250, key="clipper_transcript")
    
    with st.expander("⚙️ Advanced Camera Settings", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Face Tracking**")
            sensitivity = st.slider("Sensitivity", 1, 10, 5, help="Higher = Faster switching", key="clipper_sens")
            zoom_threshold = st.slider("Zoom Threshold", 5.0, 30.0, 20.0, help="Lower = Easier zoom", key="clipper_zoom_th")
            
        with col2:
            st.markdown("**Camera Motion**")
            smoothing = st.slider("Smoothing", 0.05, 0.5, 0.25, help="Higher = Faster movement", key="clipper_smooth")
            zoom_level = st.slider("Zoom Amount", 1.0, 1.5, 1.15, help="1.15 = 15% Zoom", key="clipper_zoom_lvl")

    # --- 4. CAPTION SETTINGS & PREVIEW ---

    st.markdown("---")
    col_cap_settings, col_cap_preview = st.columns([1, 1])
    
    with col_cap_settings:
        st.write("**Captions Setting**")
        
        # --- PRESET MANAGEMENT ---
        with st.expander("💾 Load / Save Preset", expanded=False):
            presets = load_presets()
            preset_names = ["-- Select Preset --"] + list(presets.keys())
            
            # Load
            c_load1, c_load2 = st.columns([3, 1], vertical_alignment="bottom")
            with c_load1:
                selected_preset = st.selectbox("Load Preset", preset_names, label_visibility="collapsed", key="preset_loader")
            with c_load2:
                if st.button("Load", use_container_width=True, key="btn_load_preset"):
                    if selected_preset and selected_preset != "-- Select Preset --":
                        apply_preset(presets[selected_preset])
                        st.rerun()
            
            # Save
            c_save1, c_save2 = st.columns([3, 1], vertical_alignment="bottom")
            with c_save1:
                new_preset_name = st.text_input("New Preset Name", placeholder="My Custom Style", key="preset_saver_name")
            with c_save2:
                if st.button("Save", use_container_width=True, key="btn_save_preset"):
                    if new_preset_name:
                        if new_preset_name in presets:
                            st.session_state.confirm_overwrite = new_preset_name
                            st.rerun()
                        else:
                            # Gather current settings
                            current_data = {k: st.session_state[k] for k in get_default_settings().keys() if k in st.session_state}
                            save_preset(new_preset_name, current_data)
                            st.success(f"Saved!")
                            time.sleep(1)
                            st.rerun()

            # Overwrite Confirmation
            if st.session_state.get("confirm_overwrite") == new_preset_name and new_preset_name:
                st.warning(f"⚠️ Preset '{new_preset_name}' already exists. Overwrite?")
                col_ow1, col_ow2 = st.columns(2)
                with col_ow1:
                        if st.button("✅ Yes, Overwrite", type="primary", use_container_width=True, key="btn_conf_overwrite"):
                            current_data = {k: st.session_state[k] for k in get_default_settings().keys() if k in st.session_state}
                            save_preset(new_preset_name, current_data)
                            st.session_state.confirm_overwrite = None
                            st.success("Updated!")
                            time.sleep(1)
                            st.rerun()
                with col_ow2:
                        if st.button("❌ Cancel", use_container_width=True, key="btn_cancel_overwrite"):
                            st.session_state.confirm_overwrite = None
                            st.rerun()

            # Delete
            if selected_preset and selected_preset != "-- Select Preset --":
                if "confirm_delete" not in st.session_state:
                    st.session_state.confirm_delete = None

                if st.session_state.confirm_delete != selected_preset:
                    if st.button("Delete Preset", type="secondary", use_container_width=True, key="btn_del_preset"):
                        st.session_state.confirm_delete = selected_preset
                        st.rerun()
                else:
                    st.warning(f"⚠️ Delete '{selected_preset}'?")
                    col_conf1, col_conf2 = st.columns(2)
                    with col_conf1:
                        if st.button("✅ Yes, Delete", type="primary", use_container_width=True, key="btn_conf_del"):
                            delete_preset(selected_preset)
                            st.session_state.confirm_delete = None
                            st.rerun()
                    with col_conf2:
                        if st.button("❌ Cancel", use_container_width=True, key="btn_cancel_del"):
                            st.session_state.confirm_delete = None
                            st.rerun()
            
        with st.expander("📝 Caption Configuration", expanded=False):
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
                # Grouping all colors here
                col_colors = st.columns(3)
                with col_colors[0]:
                    line_color = st.color_picker("Text Color", key="cfg_line_color")
                with col_colors[1]:
                    word_color = st.color_picker("Highlight", key="cfg_word_color")
                with col_colors[2]:
                    outline_color = st.color_picker("Outline", key="cfg_outline_color")
                
            # Layout Settings
            
            # Ensure position index
            pos_opts = ["bottom_center", "bottom_left", "bottom_right", "top_center", "top_left", "top_right", "center"]
            curr_pos = st.session_state.get("cfg_position", "bottom_center")
            pos_idx = pos_opts.index(curr_pos) if curr_pos in pos_opts else 0

            c3, c4 = st.columns(2)
            with c3:
                max_words = st.number_input("Max Words/Line", 2, 10, key="cfg_max_words")
                outline_width = st.number_input("Outline Width", 0, 50, key="cfg_outline_width")
            with c4:
                margin_v = st.number_input("Vertical Margin (px)", 0, 1000, help="Distance from vertical edge", key="cfg_margin_v")
                position = st.selectbox("Position", pos_opts, index=pos_idx, key="cfg_position")

            # Toggles
            st.write("**Text Style**")
            c_toggles = st.columns(3) # Use 3 columns for 3 toggles
            with c_toggles[0]:
                is_bold = st.checkbox("Bold Text", key="cfg_bold")
            with c_toggles[1]:
                is_italic = st.checkbox("Italic Text", key="cfg_italic")
            with c_toggles[2]:
                is_all_caps = st.checkbox("All Caps", key="cfg_all_caps")

    with col_cap_preview:
        
        # --- Preview Calculation Logic (Same as before) ---
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
                pass
        
        # 1. Scale Factors
        SCALE = 0.25 
        
        # 2. Font Size
        # Correction: User visual preference 130 input -> ~80 scale visual
        FONT_SCALE_CORRECTION = 0.615 
        preview_font_size = int(font_size * SCALE * FONT_SCALE_CORRECTION)
        
        # 3. Margins
        scaled_margin = int(margin_v * SCALE)
        
        # 4. Outline
        # Restore * 2 because CSS text-stroke is centered (half-in/half-out), 
        # while ASS/FFmpeg outline is border (all-out). We need 2x CSS to match ASS appearance.
        scaled_outline = max(0, outline_width * SCALE * 2) 
        
        # CSS for outline
        outline_css = ""
        if scaled_outline > 0:
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
        raw_text = "Sample Caption Text"
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
<div style="position: relative; width: 270px; min-width: 270px; height: 480px; margin: 0 auto; background-image: url('{meta['thumbnail']}'); background-size: cover; background-position: center; border-radius: 8px; overflow: hidden; display: flex; flex-direction: column; justify-content: {css_align_items}; align-items: {css_justify}; border: 2px solid #ddd;">
<div style="margin-top: {style_margin_top}; margin-bottom: {style_margin_bottom}; padding: 10px; text-align: {css_text_align}; width: 100%;">
<p style="font-family: '{preview_font_family}', sans-serif; font-size: {preview_font_size}px; font-weight: {css_weight}; font-style: {css_style}; margin: 0; line-height: 1.2; {outline_css}">
{preview_html}
</p>

</div>
</div>
""", unsafe_allow_html=True)


# ==================== 5. THUMBNAIL GENERATOR (MERGED) ====================
# Only show if we have metadata
if st.session_state.get('meta_data'):
    st.markdown("---")

    meta = st.session_state['meta_data']
    thumb_video_url = meta.get('video_url', '')

    # Initialize fonts for this section (Scope fix)
    font_map = get_available_fonts_map()
    available_font_names = list(font_map.keys())

    col_thumb_settings, col_thumb_preview = st.columns([1, 1])

    with col_thumb_settings:
        st.write("**Thumbnail Settings**")

        # --- PRESET MANAGER ---
        thumb_presets = load_thumb_presets()
        thumb_preset_names = list(thumb_presets.keys())
        thumb_preset_options = ["None"] + thumb_preset_names
        
        def on_thumb_preset_change():
            sel = st.session_state.get("thumb_preset_selector", "None")
            if sel != "None":
                apply_thumb_preset(sel)

        # --- PRESET MANAGER (Matched Section 4) ---
        with st.expander("💾 Load / Save Preset", expanded=False):
            thumb_presets = load_thumb_presets()
            thumb_preset_names = ["-- Select Preset --"] + list(thumb_presets.keys())
            
            # Load
            c_tp_load1, c_tp_load2 = st.columns([3, 1], vertical_alignment="bottom")
            with c_tp_load1:
                t_sel_preset = st.selectbox("Load Preset", thumb_preset_names, label_visibility="collapsed", key="thumb_preset_loader")
            with c_tp_load2:
                if st.button("Load", use_container_width=True, key="btn_load_thumb_preset"):
                    if t_sel_preset and t_sel_preset != "-- Select Preset --":
                        apply_thumb_preset(t_sel_preset)
                        st.rerun()

            # Save
            c_tp_save1, c_tp_save2 = st.columns([3, 1], vertical_alignment="bottom")
            with c_tp_save1:
                t_new_preset_name = st.text_input("New Preset Name", placeholder="My Custom Style", key="thumb_preset_saver_name")
            with c_tp_save2:
                if st.button("Save", use_container_width=True, key="btn_save_thumb_preset"):
                    if t_new_preset_name:
                        if t_new_preset_name in thumb_presets:
                            st.session_state.thumb_confirm_overwrite = t_new_preset_name
                            st.rerun()
                        else:
                            save_thumb_preset(t_new_preset_name)
                            st.success(f"Saved!")
                            time.sleep(1)
                            st.rerun()

            # Overwrite Confirmation
            if st.session_state.get("thumb_confirm_overwrite") == t_new_preset_name and t_new_preset_name:
                st.warning(f"⚠️ Preset '{t_new_preset_name}' already exists. Overwrite?")
                c_ow1, c_ow2 = st.columns(2)
                with c_ow1:
                    if st.button("✅ Yes, Overwrite", type="primary", use_container_width=True, key="btn_conf_thumb_overwrite"):
                        save_thumb_preset(t_new_preset_name)
                        st.session_state.thumb_confirm_overwrite = None
                        st.success("Updated!")
                        time.sleep(1)
                        st.rerun()
                with c_ow2:
                    if st.button("❌ Cancel", use_container_width=True, key="btn_cancel_thumb_overwrite"):
                        st.session_state.thumb_confirm_overwrite = None
                        st.rerun()


            
            # Delete (Exact Match to Section 4 Logic)
            if t_sel_preset and t_sel_preset != "-- Select Preset --":
                if "thumb_confirm_delete" not in st.session_state:
                    st.session_state.thumb_confirm_delete = None

                if st.session_state.thumb_confirm_delete != t_sel_preset:
                    if st.button("Delete Preset", use_container_width=True, key="btn_del_thumb_preset"):
                         st.session_state.thumb_confirm_delete = t_sel_preset
                         st.rerun()
                else:
                    st.warning(f"⚠️ Delete preset '{t_sel_preset}'?")
                    c_del1, c_del2 = st.columns(2)
                    with c_del1:
                        if st.button("✅ Yes, Delete", type="primary", use_container_width=True, key="btn_conf_del_thumb"):
                            delete_thumb_preset(t_sel_preset)
                            st.session_state.thumb_confirm_delete = None
                            st.success("Deleted!")
                            time.sleep(1)
                            st.rerun()
                    with c_del2:
                        if st.button("❌ Cancel", use_container_width=True, key="btn_cancel_del_thumb"):
                             st.session_state.thumb_confirm_delete = None
                             st.rerun()


        
        # Text Inputs
        # Text Inputs (Locked to YouTube Title, hidden from UI)
        thumb_text = meta.get('title', 'EPIC MOMENT')
        
        # Typography
        # --- CONFIGURATION UI (Refined & Compact) ---
        
        # 1. Typography
        with st.expander("Aa Typography & Colors", expanded=False):
            # Row 1: Main Font Settings
            c_f1, c_f2, c_f3 = st.columns([3, 1, 1])
            with c_f1:
                if "thumb_font" not in st.session_state:
                     st.session_state.thumb_font = "Poppins" if "Poppins" in available_font_names else available_font_names[0]
                t_font = st.selectbox("Font Family", available_font_names, key="thumb_font")
            with c_f2:
                if "thumb_weight" not in st.session_state:
                    st.session_state.thumb_weight = "bold"
                t_weight = st.selectbox("Weight", ["bold", "regular", "light"], key="thumb_weight")
            with c_f3:
                if "thumb_size" not in st.session_state: st.session_state.thumb_size = 100
                t_size = st.number_input("Size", 40, 300, step=10, key="thumb_size")

            # Row 2: Colors & Stroke
            c_c1, c_c2, c_c3, c_c4 = st.columns(4)
            with c_c1:
                if "thumb_color" not in st.session_state: st.session_state.thumb_color = "#FFFFFF"
                t_color = st.color_picker("Text", key="thumb_color")
            with c_c2:
                if "thumb_stroke_color" not in st.session_state: st.session_state.thumb_stroke_color = "#333333"
                t_stroke_color = st.color_picker("Stroke", key="thumb_stroke_color")
            with c_c3:
                if "thumb_shadow_color" not in st.session_state: st.session_state.thumb_shadow_color = "#904F26"
                t_shadow_color = st.color_picker("Shadow", key="thumb_shadow_color")
            with c_c4:
                if "thumb_stroke_width" not in st.session_state: st.session_state.thumb_stroke_width = 2
                t_stroke_width = st.number_input("Strk Width", 0, 20, key="thumb_stroke_width")

            # Row 3: Spacing & Transform
            c_s1, c_s2, c_s3 = st.columns(3)
            with c_s1:
                if "thumb_transform" not in st.session_state: st.session_state.thumb_transform = "capitalize"
                t_transform = st.selectbox("Case", ["capitalize", "uppercase", "lowercase", "none"], key="thumb_transform")
            with c_s2:
                if "thumb_spacing" not in st.session_state: st.session_state.thumb_spacing = 1
                t_spacing = st.number_input("Spacing", 0, 50, key="thumb_spacing")
            with c_s3:
                if "thumb_line_height" not in st.session_state: st.session_state.thumb_line_height = 1.2
                t_line_height = st.number_input("Line Height", 0.8, 2.0, step=0.1, key="thumb_line_height")

        # 2. Background & Layout
        with st.expander("🖼️ Background & Position", expanded=False):
            # Row 1: Toggles + Color
            c_b1, c_b2, c_b3, c_b4 = st.columns(4)
            with c_b1:
                if "thumb_bg_enable" not in st.session_state: st.session_state.thumb_bg_enable = True
                bg_enabled = st.toggle("Background", key="thumb_bg_enable")
            with c_b2:
                if "thumb_bg_full" not in st.session_state: st.session_state.thumb_bg_full = True
                bg_full_width = st.toggle("Full Width", disabled=not bg_enabled, key="thumb_bg_full")
            with c_b3:
                if "thumb_bg_gradient" not in st.session_state: st.session_state.thumb_bg_gradient = True
                bg_gradient = st.toggle("Gradient", disabled=not bg_enabled, key="thumb_bg_gradient")
            with c_b4:
                 if "thumb_grad_height" not in st.session_state: st.session_state.thumb_grad_height = 1000
                 bg_grad_height = st.number_input("Grad H", 0, 2000, disabled=not bg_enabled, key="thumb_grad_height")

            # Row 2: Color Input + Position + Max Lines
            c_p1, c_p2, c_p3, c_p4, c_p5 = st.columns([2, 1, 1, 1, 1])
            with c_p1:
                 # RGBA Logic
                 # 1. Parse current (default)
                 cur_rgba = st.session_state.get("thumb_bg_color", "rgba(255, 170, 0, 1.9)")
                 def_hex = "#FFAA00"
                 def_alpha = 1.0
                 try:
                     # Simple parsing
                     if "rgba" in cur_rgba:
                         parts = cur_rgba.replace("rgba(", "").replace(")", "").split(",")
                         r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
                         def_alpha = float(parts[3])
                         def_hex = '#{:02x}{:02x}{:02x}'.format(r, g, b)
                 except: 
                     pass

                 # Force update pickers if out of sync with thumb_bg_color (e.g. from preset load)
                 # This logic ensures the picker reflects the actual value, avoiding "default value" warnings
                 if "thumb_bg_hex_picker" not in st.session_state or st.session_state.thumb_bg_hex_picker != def_hex:
                     st.session_state.thumb_bg_hex_picker = def_hex
                 if "thumb_bg_alpha_picker" not in st.session_state or st.session_state.thumb_bg_alpha_picker != def_alpha:
                     st.session_state.thumb_bg_alpha_picker = def_alpha

                 c_bg_hex, c_bg_alpha = st.columns([1, 1])
                 with c_bg_hex:
                     new_hex = st.color_picker("Color", disabled=not bg_enabled, key="thumb_bg_hex_picker")
                 with c_bg_alpha:
                     new_alpha = st.number_input("Opacity", 0.0, 2.0, step=0.1, disabled=not bg_enabled, key="thumb_bg_alpha_picker")
                
                 # Reconstruct
                 h = new_hex.lstrip('#')
                 rgb = tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
                 bg_color = f"rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {new_alpha})"
                 st.session_state['thumb_bg_color'] = bg_color
            with c_p2:
                 if "thumb_pos_y" not in st.session_state: st.session_state.thumb_pos_y = "bottom"
                 pos_y = st.selectbox("Y-Pos", ["bottom", "center", "top"], key="thumb_pos_y")
            with c_p3:
                 if "thumb_margin_btm" not in st.session_state: st.session_state.thumb_margin_btm = 150
                 pos_margin_btm = st.number_input("Margin", 0, 500, key="thumb_margin_btm")
            with c_p4:
                 if "thumb_edge_pad" not in st.session_state: st.session_state.thumb_edge_pad = 10
                 pos_edge_pad = st.number_input("Padding", 0, 100, key="thumb_edge_pad")
            with c_p5:
                 if "thumb_max_lines" not in st.session_state: st.session_state.thumb_max_lines = 4
                 pos_max_lines = st.number_input("M-Lines", 1, 5, key="thumb_max_lines")
            
            if not bg_enabled:
                 bg_full_width = False
                 bg_gradient = False
                 bg_color = "rgba(0,0,0,0)"
                 bg_grad_height = 0

    with col_thumb_preview:
        
        # --- Preview Calculation for Thumbnail ---
        # 1. Scale Factors (Visual approximation for small UI)
        THUMB_SCALE = 0.25 
        
        # Font Embedding (Reuse logic if same font, or load new)
        t_font_base64 = ""
        t_font_mime = "font/ttf"
        t_selected_filename = font_map.get(t_font)
        
        if t_selected_filename:
             try:
                t_file_path = os.path.join("/app/fonts", t_selected_filename)
                if os.path.exists(t_file_path):
                    with open(t_file_path, "rb") as f:
                        t_font_bytes = f.read()
                        t_font_base64 = base64.b64encode(t_font_bytes).decode()
                        if t_selected_filename.lower().endswith(".otf"):
                            t_font_mime = "font/otf"
             except Exception:
                 pass

        t_custom_css = ""
        t_safe_family = "sans-serif"
        if t_font_base64:
            # ISOLATION FIX: Append "Thumb" to avoid collision with Section 4's CSS
            # The logic remains same (Normal weight forced), but the NAME must be unique.
            t_safe_family = ''.join(c for c in t_font if c.isalnum()) + "Thumb"
            
            # Flush-left CSS to avoid indentation issues
            t_custom_css = f"""
<style>
@font-face {{
    font-family: '{t_safe_family}';
    src: url(data:{t_font_mime};base64,{t_font_base64}) format('{ "opentype" if "otf" in t_font_mime else "truetype" }');
    font-weight: normal;
    font-style: normal;
    font-display: block; 
}}
</style>
"""
            st.markdown(t_custom_css, unsafe_allow_html=True)

        # Style Calcs
        p_font_size = int(t_size * THUMB_SCALE)
        p_stroke = max(0, t_stroke_width * THUMB_SCALE * 2)
        p_stroke_css = f"-webkit-text-stroke: {p_stroke}px {t_stroke_color};" if p_stroke > 0 else ""
        p_letter_spacing = f"{t_spacing * THUMB_SCALE}px"
        p_shadow = f"2.5px 2.5px 0px {t_shadow_color}"
        
        # Max Lines (Line Clamp logic)
        p_line_clamp_css = f"""
            display: -webkit-box;
            -webkit-line-clamp: {pos_max_lines};
            -webkit-box-orient: vertical;
            overflow: hidden;
            text-overflow: ellipsis;
        """

        # Font Weight Mapping (Match Section 4: Use strings)
        # Detailed logic: 
        # Section 4 simply maps Checkbox False->normal, True->bold.
        # We simulate this with Selectbox.
        weight_map = {"bold": "bold", "regular": "normal", "light": "lighter"}
        p_weight = weight_map.get(t_weight, "normal")

        # Text Transform
        p_text = thumb_text
        if t_transform == "uppercase": p_text = p_text.upper()
        elif t_transform == "lowercase": p_text = p_text.lower()
        elif t_transform == "capitalize": p_text = p_text.title()

        # Backend Constants (approximate)
        BACKEND_BG_PADDING = 40
        
        # Layout Calcs for Text Container
        # The text container itself will be positioned
        p_justify = "center" # Horizontal
        p_align = "flex-end" # Vertical
        p_margin_top = "0"
        p_margin_bottom = "0"
        
        # FIX: Do not add BACKEND_BG_PADDING to margin. Backend logic treats margin as distance from edge to box bottom.
        effective_margin = pos_margin_btm 
        scale_margin_btm = int(effective_margin * THUMB_SCALE)

        if pos_y == "top":
             p_align = "flex-start"
             # Top uses margin_top (default 0) + edge_padding + bg_padding. 
             # Here we simplified input to just "Margin Bottom", but let's treat it as "Margin" generic
             p_margin_top = f"{scale_margin_btm}px"
        elif pos_y == "center":
             p_align = "center"
        else:
             p_align = "flex-end"
             p_margin_bottom = f"{scale_margin_btm}px"

        # Background Logic
        # We separate Gradient rendering from Text rendering to match backend "full width gradient" behavior
        
        # 1. Text Background (Solid/Box)
        text_bg_css = ""
        box_padding_css = "padding: 0;"
        
        if bg_enabled:
             scaled_padding = int(BACKEND_BG_PADDING * THUMB_SCALE)
             box_padding_css = f"padding: {scaled_padding}px;"
             
             if not bg_gradient:
                 # Solid Mode
                 text_bg_css = f"background-color: {bg_color}; border-radius: 4px;"
                 if not bg_full_width:
                     text_bg_css += " width: auto;"
                 else:
                     text_bg_css += " width: 100%;"

        # 2. Gradient Background (Absolute Overlay)
        gradient_html = ""
        if bg_enabled and bg_gradient:
             scaled_grad_h = int(bg_grad_height * THUMB_SCALE)
             # Gradient is typically bottom-up. 
             # FIX: Use a stronger start (30%) to simulate "pekat" (intense) look requested by user
             gradient_html = f"""<div style="position: absolute; bottom: 0; left: 0; width: 100%; height: {scaled_grad_h}px; background: linear-gradient(to top, {bg_color} 50%, transparent 100%); z-index: 1;"></div>"""

        # FIX: Update shadow scale (10px * 0.25 = 2.5px)
        # p_shadow = f"2.5px 2.5px 0px {t_shadow_color}" # Already calculated above

        # Render HTML
        # FIX: Fixed Width Container (270px) to ensure font size (px) is proportional to 0.25 scale of 1080p
        # FIX: Added p_line_clamp_css and p_weight
        preview_html_template = f"""
<div style="position: relative; width: 270px; min-width: 270px; height: {int(270 * 16/9)}px; margin: 0 auto; background-image: url('{meta['thumbnail']}'); background-size: cover; background-position: center; border-radius: 8px; overflow: hidden; display: flex; flex-direction: column; justify-content: {p_align}; align-items: center; border: 2px solid #ddd;">
    {gradient_html}
    <div style="z-index: 2; margin-top: {p_margin_top}; margin-bottom: {p_margin_bottom}; text-align: center; {text_bg_css} {box_padding_css}">
        <p style="font-family: '{t_safe_family}', sans-serif; font-size: {p_font_size}px; font-weight: {p_weight}; color: {t_color}; line-height: {t_line_height}; letter-spacing: {p_letter_spacing}; margin: 0; {p_stroke_css} text-shadow: {p_shadow}; white-space: pre-wrap; {p_line_clamp_css}">{p_text}</p>
    </div>
    <p style="font-size: 10px; color: rgba(255,255,255,0.7); position: absolute; top: 5px; left: 5px; margin: 0; text-shadow: 1px 1px 2px black; z-index: 3;">Preview (Fixed Scale)</p>
</div>
"""
        
        st.markdown(preview_html_template, unsafe_allow_html=True)
        
        st.write("")

# ==================== 6. GENERATE ACTION ====================
if st.session_state.get('meta_data'):
    st.markdown("---")
    st.write("")
    if st.button("🚀 GENERATE CLIPPER (Webhook)", type="primary", use_container_width=True, key="btn_generate_clipper_final"):
        if not youtube_url:
             st.error("Missing Video URL.")
        else:
            # Prepare Transform
            final_transform = t_transform if t_transform != "none" else None

            # Construct Payload
            payload = {
                "youtube_url": youtube_url,
                "channel_name": channel_name,
                "transcript": transcript,
                # Clipper Params
                "parameters": {
                    "portrait": True,
                    "face_tracking": True,
                    "tracking_sensitivity": sensitivity,
                    "camera_smoothing": smoothing,
                    "zoom_threshold": zoom_threshold,
                    "zoom_level": zoom_level,
                },
                # Caption Params
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
                },
                # Thumbnail Params (New)
                "thumbnail_conf": {
                     "text_overlay": {
                         "text": thumb_text,
                         "style": {
                             "font_family": t_font,
                             "font_weight": t_weight,
                             "stroke_color": t_stroke_color,
                             "stroke_width": t_stroke_width,
                             "font_size": t_size,
                             "letter_spacing": t_spacing,
                             "line_height": t_line_height,
                             "color": t_color,
                             "text_transform": final_transform,
                             "text_shadow": f"10px 10px 0px {t_shadow_color}"
                         },
                         "background": {
                             "enabled": bg_enabled,
                             "full_width": bg_full_width,
                             "radius": 0,
                             "gradient": bg_gradient,
                             "gradient_height": bg_grad_height,
                             "color": bg_color
                         },
                         "position": {
                             "y": pos_y,
                             "margin_bottom": pos_margin_btm,
                             "edge_padding": pos_edge_pad,
                             "max_lines": pos_max_lines
                         }
                     }
                }
            }
            
            with st.spinner("Dispatching to Automa..."):
                try:
                    r = requests.post(WEBHOOK_URL, json=payload)
                    if r.status_code == 200:
                        st.success("✅ Job Submitted Successfully to Your Workflow!")
                        # st.json(payload) # Hidden per user request
                    else:
                        st.error(f"❌ Webhook Error: {r.status_code}")
                        st.write(r.text)
                except Exception as e:
                    st.error(f"Connection Failed: {e}")
