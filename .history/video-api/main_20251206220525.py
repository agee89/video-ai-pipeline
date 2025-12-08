from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import uuid
import redis
import json
import os

app = FastAPI(title="Video Auto-Clipping API")

redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))

class ProcessVideoRequest(BaseModel):
    youtube_url: str
    topics: List[str]
    portrait: bool = False
    callback_url: Optional[str] = None

class ProcessVideoResponse(BaseModel):
    status: str
    job_id: str

@app.post("/process_video", response_model=ProcessVideoResponse)
async def process_video(request: ProcessVideoRequest):
    job_id = f"job_{uuid.uuid4().hex[:8]}"
    
    job_data = {
        "job_id": job_id,
        "youtube_url": request.youtube_url,
        "topics": request.topics,
        "portrait": request.portrait,
        "callback_url": request.callback_url,
        "status": "pending"
    }
    
    redis_client.lpush("video_jobs", json.dumps(job_data))
    redis_client.set(f"job:{job_id}:status", "pending")
    
    return ProcessVideoResponse(
        status="accepted",
        job_id=job_id
    )

@app.get("/job/{job_id}")
async def get_job_status(job_id: str):
    status = redis_client.get(f"job:{job_id}:status")
    if not status:
        raise HTTPException(status_code=404, detail="Job not found")
    
    result = redis_client.get(f"job:{job_id}:result")
    
    return {
        "job_id": job_id,
        "status": status.decode(),
        "result": json.loads(result) if result else None
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}