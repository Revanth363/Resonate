from fastapi import FastAPI, APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse, Response
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
import re
import asyncio

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
# YOUTUBE AUDIO STREAMING WITH CACHING + RANGE SUPPORT
# ====================================================================

CACHE_DIR = "audio_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

def get_cache_path(query: str) -> str:
    query_hash = hashlib.md5(query.encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, f"{query_hash}.mp3")

def cleanup_old_cache(max_age_days=4):
    if not os.path.exists(CACHE_DIR):
        return
    cutoff_time = time.time() - (max_age_days * 24 * 60 * 60)
    deleted_count = 0
    for filename in os.listdir(CACHE_DIR):
        file_path = os.path.join(CACHE_DIR, filename)
        if os.path.isfile(file_path) and os.path.getmtime(file_path) < cutoff_time:
            try:
                os.remove(file_path)
                deleted_count += 1
            except Exception as e:
                logger.warning(f"Failed to delete {file_path}: {e}")
    if deleted_count > 0:
        logger.info(f"Cleaned up {deleted_count} old cache files")

@app.on_event("startup")
async def on_startup():
    cleanup_old_cache(4)
    logger.info("Server started - old cache files cleaned (older than 4 days)")

@api_router.get("/stream")
async def stream_audio(query: str, request: Request):
    if not query.strip():
        raise HTTPException(status_code=400, detail="Query required")

    logger.info(f"Stream request received: {query}")

    cache_path = get_cache_path(query)

    # ========================
    # CACHE HIT - FULL RANGE SUPPORT
    # ========================
    if os.path.exists(cache_path):
        logger.info(f"Cache hit - serving with range support: {cache_path}")

        file_size = os.path.getsize(cache_path)
        range_header = request.headers.get("Range")

        if range_header:
            # Parse Range header: bytes=start-end
            range_str = range_header.replace("bytes=", "")
            start_str, end_str = range_str.split("-", 1)
            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else file_size - 1

            if start >= file_size or end >= file_size or start > end:
                return Response(
                    status_code=416,
                    headers={"Content-Range": f"bytes */{file_size}"}
                )

            length = end - start + 1

            def range_generator():
                with open(cache_path, "rb") as f:
                    f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk_size = min(65536, remaining)
                        chunk = f.read(chunk_size)
                        if not chunk:
                            break
                        yield chunk
                        remaining -= len(chunk)

            headers = {
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(length),
                "Content-Type": "audio/mpeg",
                "Access-Control-Allow-Origin": "https://resonate-omega.vercel.app",
                "Access-Control-Expose-Headers": "Content-Range, Accept-Ranges, Content-Length",
                "Cache-Control": "no-cache",
            }

            return StreamingResponse(
                range_generator(),
                status_code=206,
                media_type="audio/mpeg",
                headers=headers
            )

        # No range requested → full file
        return FileResponse(
            cache_path,
            media_type="audio/mpeg",
            headers={
                "Accept-Ranges": "bytes",
                "Access-Control-Allow-Origin": "https://resonate-omega.vercel.app",
                "Cache-Control": "no-cache",
            }
        )

    # ========================
    # NO CACHE - STREAM FROM YT-DLP + CACHE + RANGE (partial support)
    # ========================
    clean_query = re.sub(r"['’\"]", "", query)
    clean_query = re.sub(r"[()[\]{}]", "", clean_query)
    clean_query = re.sub(r"\s+", " ", clean_query)
    clean_query = clean_query.strip()

    search_query = f"ytsearch1:{clean_query}"

    logger.info(f"Cleaned query: {clean_query}")
    logger.info(f"Using ytsearch1: {search_query}")

    cmd = [
        "yt-dlp",
        "--cookies", "/app/cookies.txt",
        "-f", "bestaudio[ext=m4a]/bestaudio/best",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "192K",
        "-o", "-",
        "--quiet",
        "--no-playlist",
        "--no-warnings",
        search_query
    ]

    logger.info(f"Launching yt-dlp: {' '.join(cmd)}")

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    async def log_stderr():
        while True:
            line = await process.stderr.readline()
            if not line:
                break
            logger.error(f"yt-dlp stderr: {line.decode().strip()}")

    stderr_task = asyncio.create_task(log_stderr())

    async def stream_and_cache():
        try:
            with open(cache_path, "wb") as f:
                while True:
                    chunk = await process.stdout.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    yield chunk

            await process.wait()
            await stderr_task

            if process.returncode != 0:
                logger.error(f"yt-dlp exited with code {process.returncode}")
                if os.path.exists(cache_path):
                    os.remove(cache_path)
                raise HTTPException(status_code=500, detail="yt-dlp failed to extract audio")

        except Exception as e:
            logger.error(f"Stream/cache error: {e}")
            if os.path.exists(cache_path):
                os.remove(cache_path)
            raise HTTPException(status_code=500, detail="Stream failed")

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": "audio/mpeg",
        "Access-Control-Allow-Origin": "https://resonate-omega.vercel.app",
        "Access-Control-Expose-Headers": "Accept-Ranges, Content-Range, Content-Length",
        "Cache-Control": "no-cache",
    }

    return StreamingResponse(
        stream_and_cache(),
        media_type="audio/mpeg",
        headers=headers
    )

# -------- Spotify Routes --------
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(playlists.router, prefix="/playlists", tags=["playlists"])
api_router.include_router(search.router, prefix="/search", tags=["search"])
api_router.include_router(library.router, prefix="/library", tags=["library"])
api_router.include_router(playback.router, prefix="/playback", tags=["playback"])

# -------- Attach Router --------
app.include_router(api_router)

# -------- CORS (must be last!) --------
cors_str = os.getenv("CORS_ORIGINS", "https://resonate-omega.vercel.app,http://localhost:5173,http://127.0.0.1:5173")
origins = [origin.strip() for origin in cors_str.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)