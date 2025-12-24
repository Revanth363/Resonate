from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from services.spotify_service import SpotifyService
import logging

logger = logging.getLogger(__name__)
router = APIRouter()
spotify_service = SpotifyService()


class PlaybackRequest(BaseModel):
    uris: List[str]
    device_id: Optional[str] = None
    position_ms: int = 0


class PauseRequest(BaseModel):
    device_id: Optional[str] = None


@router.post("/play")
async def start_playback(request: PlaybackRequest, access_token: str = Query(...)):
    """Start or resume playback"""
    try:
        spotify_service.start_playback(
            access_token,
            device_id=request.device_id,
            uris=request.uris,
            position_ms=request.position_ms
        )
        return {"status": "playing"}
    except Exception as e:
        logger.error(f"Error starting playback: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/pause")
async def pause_playback(request: PauseRequest, access_token: str = Query(...)):
    """Pause playback"""
    try:
        spotify_service.pause_playback(access_token, device_id=request.device_id)
        return {"status": "paused"}
    except Exception as e:
        logger.error(f"Error pausing playback: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/state")
async def get_playback_state(access_token: str = Query(...)):
    """Get current playback state"""
    try:
        state = spotify_service.get_playback_state(access_token)
        return state
    except Exception as e:
        logger.error(f"Error getting playback state: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/devices")
async def get_devices(access_token: str = Query(...)):
    """Get available devices"""
    try:
        devices = spotify_service.get_available_devices(access_token)
        return devices
    except Exception as e:
        logger.error(f"Error getting devices: {e}")
        raise HTTPException(status_code=400, detail=str(e))