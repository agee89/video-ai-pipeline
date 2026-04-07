
import os
import subprocess
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def find_font_file(font_family: str, bold: bool = False, italic: bool = False) -> str:
    """
    Find font file path using robust strategy mirrored from thumbnail.py.
    """
    font_weight = "bold" if bold else "regular"
    
    print(f"Searching for font: '{font_family}' (bold={bold}, italic={italic})")

    # 1. Try fc-list (fontconfig) first
    try:
        query = f":family={font_family}"
        if bold:
            query += ":style=Bold"
        elif italic:
            query += ":style=Italic"
            
        print(f"Running fc-list with query: {query}")
        result = subprocess.run(
            ['fc-list', query, '-f', '%{file}\\n'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            font_paths = result.stdout.strip().split('\n')
            for font_path in font_paths:
                if os.path.exists(font_path):
                    logger.info(f"Font found via fc-list: {font_path}")
                    return font_path
        else:
            print("fc-list returned no results")
    except Exception as e:
        logger.debug(f"fc-list search failed: {e}")
    
    # 2. Manual Search in known directories
    font_dirs = [
        "/app/fonts",
        "/usr/share/fonts/truetype",
        "/usr/share/fonts/truetype/dejavu",
        "/usr/share/fonts/truetype/montserrat",
    ]
    
    # Normalize input
    font_family_normalized = font_family.lower().replace(" ", "").replace("-", "").replace("_", "")
    print(f"Normalized input: '{font_family_normalized}'")
    
    # Weight suffixes
    weight_suffixes = [""]
    if bold:
        weight_suffixes = ["Bold", "-Bold", "_Bold", ""]
    elif italic:
        weight_suffixes = ["Italic", "-Italic", "_Italic", ""]
    else:
        weight_suffixes = ["Regular", "-Regular", "_Regular", ""]

    # 2a. Exact/Pattern Match
    print("Strategy 2a: Exact/Pattern Match")
    for font_dir in font_dirs:
        if not os.path.exists(font_dir):
            continue
            
        for suffix in weight_suffixes:
            patterns = [
                f"{font_family}{suffix}.ttf",
                f"{font_family}{suffix}.otf",
                f"{font_family}-{suffix.replace('-', '')}.ttf" if suffix else f"{font_family}.ttf",
                f"{font_family.lower()}{suffix.lower()}.ttf",
            ]
            
            for pattern in patterns:
                font_path = os.path.join(font_dir, pattern)
                # print(f"Checking {font_path}")
                if os.path.exists(font_path):
                    logger.info(f"Font found by pattern: {font_path}")
                    return font_path

    # 2b. Fuzzy Match (The "thumbnail.py" magic)
    print("Strategy 2b: Fuzzy Match")
    for font_dir in font_dirs:
        if not os.path.exists(font_dir):
            print(f"Skipping missing dir: {font_dir}")
            continue
            
        print(f"Scanning dir: {font_dir}")
        try:
            files = os.listdir(font_dir)
            print(f"Found {len(files)} files in {font_dir}")
            for filename in files:
                if not filename.lower().endswith(('.ttf', '.otf')):
                    continue
                
                # Normalize filename
                filename_normalized = filename.lower().replace(" ", "").replace("-", "").replace("_", "").replace(".ttf", "").replace(".otf", "")
                
                match = False
                
                # Strategy 1: containment
                if font_family_normalized in filename_normalized or filename_normalized in font_family_normalized:
                    # print(f"Match S1: {filename_normalized}")
                    match = True
                
                # Strategy 2: First 5+ chars match (e.g. komikax matches komikaaxis)
                min_len = min(len(font_family_normalized), len(filename_normalized))
                if min_len >= 5 and font_family_normalized[:5] == filename_normalized[:5]:
                    # print(f"Match S2: {filename_normalized} vs {font_family_normalized}")
                    match = True
                
                # Strategy 3: First word match
                first_word = font_family.lower().split()[0] if font_family else ""
                if first_word and len(first_word) >= 4 and filename_normalized.startswith(first_word):
                    # print(f"Match S3: {filename_normalized}")
                    match = True
                
                if match:
                    font_path = os.path.join(font_dir, filename)
                    logger.info(f"Font found by fuzzy match: {font_path}")
                    return font_path

        except Exception as e:
            print(f"Error: {e}")
            continue

    # 3. Last Resort Fallback
    logger.warning(f"Font {font_family} not found. Using default.")
    return "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

if __name__ == "__main__":
    result = find_font_file("Komika Axis", bold=True)
    print(f"FINAL RESULT: {result}")
