import os
import hashlib
import subprocess
import logging
from fastapi import HTTPException
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

# Cache directory
CACHE_DIR = "audio_cache"
os.makedirs(CACHE_DIR, exist_ok=True)


def get_cache_path(query: str) -> str:
    query_hash = hashlib.md5(query.encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, f"{query_hash}.mp3")


def stream_audio(query: str):
    if not query.strip():
        raise HTTPException(status_code=400, detail="Query required")

    cache_path = get_cache_path(query)

    # 1️⃣ If cached → serve immediately (supports range/seek)
    if os.path.exists(cache_path):
        return FileResponse(
            cache_path,
            media_type="audio/mpeg",
            filename="audio.mp3"
        )

    # 2️⃣ Download + convert to MP3 (ffmpeg REQUIRED)
    temp_path = cache_path + ".part"

    cmd = [
        "yt-dlp",
        "-f", "bestaudio",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "192K",
        "-o", temp_path,
        "--no-playlist",
        f"ytsearch1:{query}"
    ]

    try:
        subprocess.run(cmd, check=True)
        os.rename(temp_path, cache_path)
    except Exception as e:
        logger.error(f"Audio download failed: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise HTTPException(status_code=500, detail="Audio processing failed")

    # 3️⃣ Serve final MP3
    return FileResponse(
        cache_path,
        media_type="audio/mpeg",
        filename="audio.mp3"
    )
