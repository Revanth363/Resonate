# Use a slim Python base (Debian-based) → smaller than full, but has apt for ffmpeg
FROM python:3.12-slim-bookworm

# Set working directory inside container
WORKDIR /app

# Install system dependencies: ffmpeg + yt-dlp requirements (curl for updates if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip and install Python dependencies first (cache-friendly layer)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of your backend code
COPY . .

# Create audio_cache folder (will be ephemeral unless you mount volume)
RUN mkdir -p /app/audio_cache && \
    chmod -R 777 /app/audio_cache  # permissive for uvicorn user

# Expose the port FastAPI will run on (Render/Railway/Fly ignore this but good practice)
EXPOSE 8000

# Run with uvicorn (production style: workers, host 0.0.0.0)
# Adjust --workers based on your plan (1-2 for free tiers)
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "${PORT:-8000}", "--workers", "1"]