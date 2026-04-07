"""
Video Composer Module
Allows executing complex FFmpeg commands by defining inputs, filter chains, and output variables.
"""

import subprocess
import os
import logging
import time
import requests
import re
import uuid
from typing import List, Dict, Optional, Union

logger = logging.getLogger(__name__)

def download_file(url: str, output_path: str) -> str:
    """Download file from URL to local path"""
    internal_url = url
    
    # Handle hostname conflicts
    internal_url = re.sub(r'http://minio:9000/', 'http://minio-nca:9000/', internal_url)
    internal_url = re.sub(r'http://localhost:9000/', 'http://minio-nca:9000/', internal_url)
    
    # Handle new minio-storage endpoint (port 9002)
    internal_url = re.sub(r'http://localhost:9002/', 'http://minio-storage:9002/', internal_url)
    internal_url = re.sub(r'http://127.0.0.1:9002/', 'http://minio-storage:9002/', internal_url)
    internal_url = internal_url.replace("minio_storage", "minio-storage")
    
    # Handle misconfigured n8n URL
    internal_url = re.sub(r'http://n8n-ncat:5678/', 'http://minio-storage:9002/', internal_url)
    internal_url = internal_url.replace("http://minio:9002/", "http://minio-storage:9002/")
    internal_url = internal_url.replace("minio-video", "minio-storage")
    
    logger.info(f"Downloading: {internal_url}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Ch-Ua": '"Chromium";v="120", "Google Chrome";v="120"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"macOS"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate", 
        "Sec-Fetch-Site": "none",
        "Upgrade-Insecure-Requests": "1"
    }
    response = requests.get(internal_url, headers=headers, stream=True, timeout=120)
    response.raise_for_status()
    
    with open(output_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
            
    return output_path

def compose_video(
    job_id: str,
    inputs: List[Dict],
    filter_complex: Optional[str] = None,
    output_args: Optional[List[str]] = None,
    output_format: str = "mp4"
) -> dict:
    """
    Compose video using complex FFmpeg command.
    
    Args:
        job_id: Unique job identifier
        inputs: List of dicts, e.g., [{"url": "...", "options": ["-ss", "10"]}]
        filter_complex: FFmpeg filter_complex string
        output_args: List of output arguments, e.g., ["-c:v", "libx264"]
        output_format: Output file extension (default: mp4)
        
    Returns:
        dict: {
            "output_path": str,
            "run_time": float
        }
    """
    start_ts = time.time()
    output_dir = "/app/output"
    output_path = f"{output_dir}/{job_id}.{output_format}"
    
    downloaded_files = []
    
    try:
        cmd = ["ffmpeg", "-y"]
        
        # 1. Process Inputs
        for i, input_item in enumerate(inputs):
            url = input_item.get("url")
            options = input_item.get("options", [])
            
            if not url:
                continue
                
            # Determine extension
            ext = os.path.splitext(url.split('?')[0])[1] or ".mp4"
            local_input_path = f"{output_dir}/{job_id}_input_{i}{ext}"
            
            # Download file
            download_file(url, local_input_path)
            downloaded_files.append(local_input_path)
            
            # Add input options (before -i)
            if options:
                cmd.extend(options)
                
            cmd.extend(["-i", local_input_path])
            
        # 2. Add Filter Complex
        if filter_complex:
            cmd.extend(["-filter_complex", filter_complex])
            
        # 3. Add Output Arguments
        if output_args:
            cmd.extend(output_args)
            
        # Add output path
        cmd.append(output_path)
        
        logger.info(f"Running compose command: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            logger.error(f"FFmpeg compose error: {result.stderr}")
            raise Exception(f"FFmpeg failed: {result.stderr}")
            
        run_time = time.time() - start_ts
        
        return {
            "output_path": output_path,
            "run_time": run_time
        }
        
    finally:
        # Cleanup input files
        for path in downloaded_files:
            if os.path.exists(path):
                os.remove(path)
