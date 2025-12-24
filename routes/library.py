from fastapi import APIRouter, HTTPException, Query
from services.spotify_service import SpotifyService
import logging

logger = logging.getLogger(__name__)
router = APIRouter()
spotify_service = SpotifyService()


@router.get("/tracks")
async def get_saved_tracks(access_token: str = Query(...), limit: int = Query(50)):
    """Get user's saved tracks"""
    try:
        tracks = spotify_service.get_user_saved_tracks(access_token, limit)
        return tracks
    except Exception as e:
        logger.error(f"Error getting saved tracks: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/recently-played")
async def get_recently_played(access_token: str = Query(...), limit: int = Query(20)):
    """Get recently played tracks"""
    try:
        tracks = spotify_service.get_recently_played(access_token, limit)
        return tracks
    except Exception as e:
        logger.error(f"Error getting recently played: {e}")
        raise HTTPException(status_code=400, detail=str(e))