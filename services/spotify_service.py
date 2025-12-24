import os
from spotipy import Spotify
from spotipy.oauth2 import SpotifyOAuth
from spotipy.cache_handler import MemoryCacheHandler


class SpotifyService:
    def __init__(self):
        # 🔥 FIXED ENV VARIABLE NAMES
        self.client_id = os.environ.get("SPOTIPY_CLIENT_ID")
        self.client_secret = os.environ.get("SPOTIPY_CLIENT_SECRET")
        self.redirect_uri = os.environ.get("SPOTIPY_REDIRECT_URI")

        self.scope = (
            "user-read-private "
            "user-read-email "
            "user-library-read "
            "playlist-read-private "
            "playlist-read-collaborative "
            "user-read-playback-state "
            "user-modify-playback-state "
            "streaming "
            "user-read-recently-played"
        )

    # ---------------- AUTH ---------------- #

    def get_auth_manager(self, cache_handler=None):
        return SpotifyOAuth(
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirect_uri=self.redirect_uri,
            scope=self.scope,
            cache_handler=cache_handler or MemoryCacheHandler(),
            show_dialog=True,
        )

    def get_authorization_url(self):
        auth_manager = self.get_auth_manager()
        return auth_manager.get_authorize_url()

    def get_access_token(self, code: str):
        auth_manager = self.get_auth_manager()
        return auth_manager.get_access_token(
            code, as_dict=True, check_cache=False
        )

    def refresh_access_token(self, refresh_token: str):
        auth_manager = self.get_auth_manager()
        return auth_manager.refresh_access_token(refresh_token)

    # ---------------- CLIENT ---------------- #

    def get_spotify_client(self, access_token: str):
        return Spotify(auth=access_token)

    # ---------------- USER ---------------- #

    def get_user_profile(self, access_token: str):
        sp = self.get_spotify_client(access_token)
        return sp.current_user()

    # ---------------- PLAYLISTS ---------------- #

    def get_user_playlists(self, access_token: str, limit: int = 50):
        sp = self.get_spotify_client(access_token)
        return sp.current_user_playlists(limit=limit)

    def get_playlist(self, access_token: str, playlist_id: str):
        sp = self.get_spotify_client(access_token)
        return sp.playlist(playlist_id)

    def get_featured_playlists(
        self,
        access_token: str,
        limit: int = 20,
        country: str = "IN",   # 🔥 REQUIRED
    ):
        sp = self.get_spotify_client(access_token)
        return sp.featured_playlists(
            limit=limit,
            country=country,
        )

    # ---------------- SEARCH ---------------- #

    def get_categories(self, access_token: str, limit: int = 20):
        sp = self.get_spotify_client(access_token)
        return sp.categories(limit=limit)

    def search(
        self,
        access_token: str,
        query: str,
        search_type: str = "track",
        limit: int = 20,
    ):
        sp = self.get_spotify_client(access_token)
        return sp.search(q=query, type=search_type, limit=limit)

    # ---------------- LIBRARY ---------------- #

    def get_user_saved_tracks(self, access_token: str, limit: int = 50):
        sp = self.get_spotify_client(access_token)
        return sp.current_user_saved_tracks(limit=limit)

    def get_recently_played(self, access_token: str, limit: int = 20):
        sp = self.get_spotify_client(access_token)
        return sp.current_user_recently_played(limit=limit)

    # ---------------- PLAYBACK ---------------- #

    def start_playback(
        self,
        access_token: str,
        device_id: str = None,
        uris: list = None,
        position_ms: int = 0,
    ):
        sp = self.get_spotify_client(access_token)
        return sp.start_playback(
            device_id=device_id,
            uris=uris,
            position_ms=position_ms,
        )

    def pause_playback(self, access_token: str, device_id: str = None):
        sp = self.get_spotify_client(access_token)
        return sp.pause_playback(device_id=device_id)

    def get_playback_state(self, access_token: str):
        sp = self.get_spotify_client(access_token)
        return sp.current_playback()

    def get_available_devices(self, access_token: str):
        sp = self.get_spotify_client(access_token)
        return sp.devices()
