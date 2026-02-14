from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from urllib.parse import urlencode
from pydantic import BaseModel
from services.spotify_service import SpotifyService
import logging
import secrets
import time
from typing import Optional

logger = logging.getLogger(__name__)
router = APIRouter()
spotify_service = SpotifyService()


class RefreshTokenRequest(BaseModel):
    refresh_token: str


@router.get("/login")
async def spotify_login(
    request: Request,
    state: Optional[str] = Query(None),
):
    """
    Generate Spotify authorization URL with optional state parameter.
    If no state is provided, a random one is generated and returned.
    """
    try:
        # Generate secure random state if not provided (CSRF protection)
        if not state:
            state = secrets.token_urlsafe(32)

        # You can store state in session/cookie if you want to verify it later
        # For simplicity here we just pass it back to frontend
        # In production: store in session or signed cookie

        auth_url = spotify_service.get_authorization_url(state=state)

        return {
            "auth_url": auth_url,
            "state": state,  # frontend should keep this and send back in callback
        }
    except Exception as e:
        logger.error(f"Error generating auth URL: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate login URL")


@router.get("/callback")
async def spotify_callback(
    code: str = Query(...),
    state: Optional[str] = Query(None),
):
    """
    Handle Spotify OAuth callback.
    Receives code and optional state.
    """
    try:
        token_info = spotify_service.get_access_token(code)

        expires_at = int(time.time()) + token_info["expires_in"]

        # Pass tokens via URL params so frontend can store them
        params = {
            "access_token": token_info["access_token"],
            "expires_in": str(token_info["expires_in"]),
            "expires_at": str(expires_at),
            "token_type": token_info.get("token_type", "Bearer"),
            "scope": token_info.get("scope", ""),
        }
        if "refresh_token" in token_info:
            params["refresh_token"] = token_info["refresh_token"]

        query_string = urlencode(params)
        frontend_callback_url = f"https://resonate-omega.vercel.app/callback?{query_string}"

        return RedirectResponse(url=frontend_callback_url)

    except Exception as e:
        logger.error(f"Callback error: {e}", exc_info=True)
        error_url = f"https://resonate-omega.vercel.app/login?error=login_failed&message={str(e)}"
        return RedirectResponse(url=error_url)
    

@router.post("/refresh")
async def refresh_token(request: RefreshTokenRequest):
    """Refresh Spotify access token using refresh token"""
    try:
        token_info = spotify_service.refresh_access_token(request.refresh_token)

        expires_at = int(time.time()) + token_info["expires_in"]

        return {
            "access_token": token_info["access_token"],
            "expires_in": token_info["expires_in"],
            "expires_at": expires_at,
            "token_type": token_info.get("token_type", "Bearer"),
            "scope": token_info.get("scope", ""),
        }
    except Exception as e:
        logger.error(f"Token refresh failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=400,
            detail=f"Failed to refresh token: {str(e)}"
        )


@router.get("/me")
async def get_current_user(access_token: str = Query(...)):
    """Get current authenticated user's profile"""
    try:
        user_profile = spotify_service.get_user_profile(access_token)
        return user_profile
    except Exception as e:
        logger.error(f"Failed to get user profile: {e}", exc_info=True)
        raise HTTPException(
            status_code=401,
            detail=f"Authentication failed or token invalid: {str(e)}"
        )