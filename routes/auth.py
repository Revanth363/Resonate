from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from services.spotify_service import SpotifyService
import logging

logger = logging.getLogger(__name__)
router = APIRouter()
spotify_service = SpotifyService()


class RefreshTokenRequest(BaseModel):
    refresh_token: str


@router.get("/login")
async def spotify_login():
    """Get Spotify authorization URL"""
    try:
        auth_url = spotify_service.get_authorization_url()
        return {"auth_url": auth_url}
    except Exception as e:
        logger.error(f"Error getting auth URL: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/callback")
async def spotify_callback(code: str = Query(...)):
    """Handle Spotify OAuth callback"""
    try:
        token_info = spotify_service.get_access_token(code)
        return {
            "access_token": token_info['access_token'],
            "refresh_token": token_info['refresh_token'],
            "expires_in": token_info['expires_in']
        }
    except Exception as e:
        logger.error(f"Error in callback: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to get access token: {str(e)}")


@router.post("/refresh")
async def refresh_token(request: RefreshTokenRequest):
    """Refresh Spotify access token"""
    try:
        token_info = spotify_service.refresh_access_token(request.refresh_token)
        return {
            "access_token": token_info['access_token'],
            "expires_in": token_info['expires_in']
        }
    except Exception as e:
        logger.error(f"Error refreshing token: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to refresh token: {str(e)}")


@router.get("/me")
async def get_current_user(access_token: str = Query(...)):
    """Get current user profile"""
    try:
        user_profile = spotify_service.get_user_profile(access_token)
        return user_profile
    except Exception as e:
        logger.error(f"Error getting user profile: {e}")
        raise HTTPException(status_code=401, detail=f"Failed to get user profile: {str(e)}")