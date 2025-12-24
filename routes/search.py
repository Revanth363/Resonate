from fastapi import APIRouter, HTTPException, Query
from services.spotify_service import SpotifyService
import logging

logger = logging.getLogger(__name__)
router = APIRouter()
spotify_service = SpotifyService()


@router.get("")
async def search(
    q: str = Query(...),
    access_token: str = Query(...),
    type: str = Query('track'),
    limit: int = Query(20)
):
    """Search for tracks, albums, artists, or playlists"""
    try:
        results = spotify_service.search(access_token, q, type, limit)
        return results
    except Exception as e:
        logger.error(f"Error searching: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/categories")
async def get_categories(access_token: str = Query(...), limit: int = Query(20)):
    """Get browse categories"""
    try:
        categories = spotify_service.get_categories(access_token, limit)
        return categories
    except Exception as e:
        logger.error(f"Error getting categories: {e}")
        raise HTTPException(status_code=400, detail=str(e))