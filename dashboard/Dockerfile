FROM python:3.11-slim

WORKDIR /app

# Install ffmpeg for yt-dlp
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip uninstall -y youtube-transcript-api || true && \
    pip install --no-cache-dir -r requirements.txt && \
    pip show youtube-transcript-api

COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0"]
