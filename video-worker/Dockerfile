FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    fonts-liberation \
    fontconfig \
    wget \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install Montserrat font
RUN mkdir -p /usr/share/fonts/truetype/montserrat \
    && wget -q "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Bold.ttf" \
         -O /usr/share/fonts/truetype/montserrat/Montserrat-Bold.ttf \
    && wget -q "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Regular.ttf" \
         -O /usr/share/fonts/truetype/montserrat/Montserrat-Regular.ttf \
    && fc-cache -f -v

# Custom fonts directory
RUN mkdir -p /app/fonts

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy custom fonts first (if any)
COPY fonts/ /app/fonts/

# Install custom fonts to system
RUN if [ -n "$(ls -A /app/fonts/*.ttf 2>/dev/null)" ]; then \
        cp /app/fonts/*.ttf /usr/share/fonts/truetype/ && \
        fc-cache -f -v; \
    fi

COPY . .

CMD ["python", "worker.py"]