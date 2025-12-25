from fastapi import FastAPI, APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List
from datetime import datetime
import uuid
import os
import logging
import subprocess
import hashlib
import time

# -------- Import Spotify Routes --------
from routes import auth, playlists, search, library, playback

# -------- Environment Setup --------
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# -------- Logging --------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------- MongoDB --------
mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

# -------- FastAPI App --------
app = FastAPI(title="Spotify Clone API", version="1.0.0")

# -------- CORS --------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://resonate-eight.vercel.app",
        # Add your production frontend URL here when deploying
        # "https://your-production-domain.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------- API Router --------
api_router = APIRouter(prefix="/api")

# -------- Health / Status Models --------
class StatusCheck(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class StatusCheckCreate(BaseModel):
    client_name: str

# -------- Base Routes --------
@api_router.get("/")
async def root():
    return {"message": "Spotify Clone API is running"}

@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status = StatusCheck(client_name=input.client_name)
    await db.status_checks.insert_one(status.dict())
    return status

@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    docs = await db.status_checks.find().to_list(1000)
    return [StatusCheck(**doc) for doc in docs]

# ====================================================================
# 🎧 YOUTUBE AUDIO STREAMING WITH CACHING & FULL SEEK SUPPORT
# ====================================================================

CACHE_DIR = "audio_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

def get_cache_path(query: str) -> str:
    """Generate cache filename using MD5 hash + .webm extension"""
    query_hash = hashlib.md5(query.encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, f"{query_hash}.webm")  # ← Correct extension

# -------- Cache Cleanup Function --------
def cleanup_old_cache(max_age_days=4):
    """Delete cached audio files older than max_age_days"""
    if not os.path.exists(CACHE_DIR):
        return
    
    cutoff_time = time.time() - (max_age_days * 24 * 60 * 60)
    deleted_count = 0
    for filename in os.listdir(CACHE_DIR):
        file_path = os.path.join(CACHE_DIR, filename)
        if os.path.isfile(file_path):
            if os.path.getmtime(file_path) < cutoff_time:
                try:
                    os.remove(file_path)
                    deleted_count += 1
                except Exception as e:
                    logger.warning(f"Failed to delete {file_path}: {e}")
    if deleted_count > 0:
        logger.info(f"Cleaned up {deleted_count} cache files older than {max_age_days} days")

# Run cleanup on server startup
@app.on_event("startup")
async def on_startup():
    cleanup_old_cache(4)
    logger.info("Server started - old cache files cleaned (older than 4 days)")

# -------- Stream Endpoint --------
@api_router.get("/stream")
async def stream_audio(query: str):
    if not query.strip():
        raise HTTPException(status_code=400, detail="Query required")

    cache_path = get_cache_path(query)

    # Serve cached file if exists
    if os.path.exists(cache_path):
        return FileResponse(
            cache_path,
            media_type="audio/webm",
            headers={"Accept-Ranges": "bytes"}
        )

    # Build yt-dlp command with extra options to help bypass common issues
    cmd = [
        "yt-dlp",
        "-f", "bestaudio",
        "-o", "-",
        "--quiet",
        "--no-warnings",
        "--no-playlist",
        "--retries", "5",
        "--fragment-retries", "5",
        "--extractor-retries", "3",
        "--sleep-requests", "1",      # Slow down requests a bit
        "--sleep-interval", "1",      # Avoid aggressive rate-limiting
        "--max-sleep-interval", "5",
        "--force-ipv4",               # Sometimes helps with cloud networking
        f"ytsearch1:{query}"
    ]

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,   # Capture errors for logging
            bufsize=1024 * 1024
        )
    except FileNotFoundError:
        logger.error("yt-dlp executable not found!")
        raise HTTPException(status_code=500, detail="Audio service unavailable")

    async def stream_and_cache():
        try:
            with open(cache_path, "wb") as f:
                while True:
                    chunk = process.stdout.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    yield chunk

            process.wait(timeout=90)
            stderr_output = process.stderr.read().decode(errors="ignore").strip()

            if process.returncode != 0:
                error_msg = stderr_output or f"yt-dlp exited with code {process.returncode}"
                logger.error(f"yt-dlp failed for query '{query}': {error_msg}")

                # Clean up partial/invalid cache file
                if os.path.exists(cache_path):
                    os.remove(cache_path)

                # DO NOT raise exception here — response already started
                # Just stop yielding → browser gets incomplete audio + connection close
                return

            logger.info(f"Successfully streamed and cached: {query}")

        except subprocess.TimeoutExpired:
            process.kill()
            logger.error("yt-dlp timed out")
            if os.path.exists(cache_path):
                os.remove(cache_path)
        except Exception as e:
            logger.error(f"Unexpected error during streaming: {e}")
            if os.path.exists(cache_path):
                os.remove(cache_path)

    return StreamingResponse(
        stream_and_cache(),
        media_type="audio/webm",
        headers={
            "Accept-Ranges": "bytes",
            "Content-Disposition": "inline",
        }
            )
    
# -------- Spotify Routes --------
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(playlists.router, prefix="/playlists", tags=["playlists"])
api_router.include_router(search.router, prefix="/search", tags=["search"])
api_router.include_router(library.router, prefix="/library", tags=["library"])
api_router.include_router(playback.router, prefix="/playback", tags=["playback"])

# -------- Attach Router --------
app.include_router(api_router)
