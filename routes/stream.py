import os
import hashlib
import subprocess
from fastapi import HTTPException
from fastapi.responses import FileResponse, StreamingResponse
import logging

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

    # If already cached → serve file (supports seeking!)
    if os.path.exists(cache_path):
        return FileResponse(
            cache_path,
            media_type="audio/mpeg",
            headers={"Accept-Ranges": "bytes"}
        )

    # Not cached → download once and cache while streaming
    cmd = [
    "yt-dlp",
    "-f", "bestaudio",
    "--extract-audio",
    "--audio-format", "mp3",
    "-o", "-",
    "--no-playlist",
    f"ytsearch1:{query}"
]


    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=1024 * 1024
    )

    def stream_and_cache():
        try:
            with open(cache_path, "wb") as f:
                while True:
                    chunk = process.stdout.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    yield chunk
            process.wait()
        except Exception as e:
            logger.error(f"Stream/cache error: {e}")
            raise

    return StreamingResponse(
        stream_and_cache(),
        media_type="audio/mpeg",
        headers={
            "Accept-Ranges": "bytes",
            "Content-Disposition": "inline"
        }
    )