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

# -------- Health Models --------
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
# AUDIO STREAMING WITH CACHE + RANGE SUPPORT
# ====================================================================

CACHE_DIR = "audio_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

def get_cache_path(query: str) -> str:
    query_hash = hashlib.md5(query.encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, f"{query_hash}.audio")

def cleanup_old_cache(max_age_days=4):
    cutoff_time = time.time() - (max_age_days * 24 * 60 * 60)
    for filename in os.listdir(CACHE_DIR):
        file_path = os.path.join(CACHE_DIR, filename)
        if os.path.isfile(file_path) and os.path.getmtime(file_path) < cutoff_time:
            try:
                os.remove(file_path)
            except:
                pass

@app.on_event("startup")
async def on_startup():
    cleanup_old_cache(4)
    logger.info("Server started - old cache cleaned")

# ========================= DEBUG ROUTE =========================
@api_router.get("/debug-formats")
async def debug_formats():
    test_url = "https://youtube.com/watch?v=Q4zUoiJE478"

    cmd = ["yt-dlp", "-F", test_url]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    stdout, stderr = await process.communicate()

    return {
        "formats": stdout.decode(),
        "errors": stderr.decode()
    }

# ========================= STREAM ROUTE =========================
@api_router.get("/stream")
async def stream_audio(query: str, request: Request):
    if not query.strip():
        raise HTTPException(status_code=400, detail="Query required")

    cache_path = get_cache_path(query)

    # ===== CACHE HIT =====
    if os.path.exists(cache_path):
        file_size = os.path.getsize(cache_path)
        range_header = request.headers.get("Range")

        if range_header:
            range_str = range_header.replace("bytes=", "")
            start_str, end_str = range_str.split("-", 1)
            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else file_size - 1

            if start >= file_size or end >= file_size or start > end:
                return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

            length = end - start + 1

            def range_generator():
                with open(cache_path, "rb") as f:
                    f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = f.read(min(65536, remaining))
                        if not chunk:
                            break
                        yield chunk
                        remaining -= len(chunk)

            return StreamingResponse(
                range_generator(),
                status_code=206,
                media_type="audio/mpeg",
                headers={
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(length),
                }
            )

        return FileResponse(cache_path, media_type="audio/mpeg")

    # ===== CACHE MISS =====
    clean_query = re.sub(r"[\"'’()[\]{}]", "", query).strip()
    search_query = f"ytsearch1:{clean_query}"

    cmd = [
        "yt-dlp",
        "--cookies", "/app/cookies.txt",
        "-f", "ba",
        "--extractor-args", "youtube:player_client=web",
        "-o", "-",
        "--quiet",
        "--no-playlist",
        search_query
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

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

            if process.returncode != 0:
                if os.path.exists(cache_path):
                    os.remove(cache_path)

        except Exception:
            if os.path.exists(cache_path):
                os.remove(cache_path)
            return

    return StreamingResponse(
        stream_and_cache(),
        media_type="audio/mpeg",
        headers={"Accept-Ranges": "bytes"}
    )

# -------- Spotify Routes --------
api_router.include_router(auth.router, prefix="/auth")
api_router.include_router(playlists.router, prefix="/playlists")
api_router.include_router(search.router, prefix="/search")
api_router.include_router(library.router, prefix="/library")
api_router.include_router(playback.router, prefix="/playback")

app.include_router(api_router)

# -------- CORS --------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
