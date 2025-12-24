from fastapi import APIRouter, HTTPException, Query
from services.spotify_service import SpotifyService
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

spotify_service = SpotifyService()


@router.get("")
async def get_user_playlists(
    access_token: str = Query(...),
    limit: int = Query(50)
):
    """Get current user's playlists"""
    try:
        return spotify_service.get_user_playlists(access_token, limit)
    except Exception as e:
        logger.error(f"Error getting playlists: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{playlist_id}")
async def get_playlist(
    playlist_id: str,
    access_token: str = Query(...)
):
    """Get playlist details"""
    try:
        return spotify_service.get_playlist(access_token, playlist_id)
    except Exception as e:
        logger.error(f"Error getting playlist {playlist_id}: {e}")
        raise HTTPException(status_code=400, detail=str(e))
