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

# ---------------- ENV ----------------
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# ---------------- LOGGING ----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("server")

# ---------------- MONGODB ----------------
mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

# ---------------- FASTAPI ----------------
app = FastAPI(title="Spotify Clone API", version="1.0.0")

# ---------------- CORS ----------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "https://resonate-eight.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_router = APIRouter(prefix="/api")

# ---------------- MODELS ----------------
class StatusCheck(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class StatusCheckCreate(BaseModel):
    client_name: str

# ---------------- BASIC ROUTES ----------------
@api_router.get("/")
async def root():
    return {"message": "API running"}

@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status = StatusCheck(client_name=input.client_name)
    await db.status_checks.insert_one(status.dict())
    return status

@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    docs = await db.status_checks.find().to_list(1000)
    return [StatusCheck(**doc) for doc in docs]

# =========================================================
# 🎧 YOUTUBE AUDIO STREAMING (FINAL & STABLE)
# =========================================================

CACHE_DIR = "audio_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

def cache_path(query: str) -> str:
    return os.path.join(
        CACHE_DIR,
        hashlib.md5(query.encode()).hexdigest() + ".webm"
    )

def cleanup_cache(days=4):
    cutoff = time.time() - days * 86400
    for f in os.listdir(CACHE_DIR):
        fp = os.path.join(CACHE_DIR, f)
        if os.path.isfile(fp) and os.path.getmtime(fp) < cutoff:
            os.remove(fp)

@app.on_event("startup")
async def startup():
    cleanup_cache()
    logger.info("Cache cleaned")

@api_router.get("/stream")
async def stream_audio(query: str):
    if not query.strip():
        raise HTTPException(400, "Query required")

    path = cache_path(query)

    # Serve cached file if valid
    if os.path.exists(path) and os.path.getsize(path) > 100_000:
        return FileResponse(
            path,
            media_type="audio/webm",
            headers={"Accept-Ranges": "bytes"}
        )

    cmd = [
        "yt-dlp",
        "--cookies", "cookies.txt",
        "--user-agent", "Mozilla/5.0",
        "-f", "bestaudio/best",          # ✅ FIX HERE
        "-o", "-",
        "--no-playlist",
        "--quiet",
        "--no-warnings",
        "--retries", "5",
        "--fragment-retries", "5",
        "--extractor-retries", "3",
        "--sleep-requests", "1",
        "--sleep-interval", "1",
        "--max-sleep-interval", "5",
        "--force-ipv4",
        f"ytsearch1:{query}"
    ]

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1024 * 1024
        )
    except FileNotFoundError:
        raise HTTPException(500, "yt-dlp not installed")

    async def generator():
        try:
            with open(path, "wb") as f:
                while True:
                    chunk = process.stdout.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    yield chunk

            process.wait(timeout=90)

            if process.returncode != 0:
                err = process.stderr.read().decode(errors="ignore")
                logger.error(f"yt-dlp failed: {err}")
                if os.path.exists(path):
                    os.remove(path)
                return

        except Exception as e:
            logger.error(f"Stream error: {e}")
            if os.path.exists(path):
                os.remove(path)

    return StreamingResponse(
        generator(),
        media_type="audio/webm",
        headers={
            "Accept-Ranges": "bytes",
            "Content-Disposition": "inline"
        }
    )

# ---------------- SPOTIFY ROUTES ----------------
from routes import auth, playlists, search, library, playback

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(playlists.router, prefix="/playlists", tags=["playlists"])
api_router.include_router(search.router, prefix="/search", tags=["search"])
api_router.include_router(library.router, prefix="/library", tags=["library"])
api_router.include_router(playback.router, prefix="/playback", tags=["playback"])

app.include_router(api_router)
