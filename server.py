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
import re

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
# YOUTUBE AUDIO STREAMING WITH CACHING
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
async def stream_audio(query: str):
    if not query.strip():
        raise HTTPException(status_code=400, detail="Query required")

    logger.info(f"Stream request received: {query}")

    cache_path = get_cache_path(query)

    if os.path.exists(cache_path):
        logger.info(f"Cache hit - serving: {cache_path}")
        return FileResponse(
            cache_path,
            media_type="audio/mpeg",
            headers={"Accept-Ranges": "bytes"}
        )

    clean_query = re.sub(r"['’\"]", "", query)
    clean_query = re.sub(r"[()[\]{}]", "", clean_query)
    clean_query = re.sub(r"\s+", " ", clean_query)
    clean_query = clean_query.strip()

    search_query = f"ytsearch1:{clean_query}"

    logger.info(f"Cleaned query: {clean_query}")
    logger.info(f"Using ytsearch1: {search_query}")

    cmd = [
        "yt-dlp",
        "-f", "bestaudio",
        "-o", "-",
        "--quiet",
        "--no-playlist",
        search_query
    ]

    logger.info(f"Launching yt-dlp: {' '.join(cmd)}")

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=1024 * 1024
    )

    async def stream_and_cache():
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
            if os.path.exists(cache_path):
                os.remove(cache_path)
            raise HTTPException(status_code=500, detail="Stream failed")

    return StreamingResponse(
        stream_and_cache(),
        media_type="audio/mpeg",
        headers={
            "Accept-Ranges": "bytes",
            "Content-Disposition": "inline"
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