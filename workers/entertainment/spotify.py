"""
Spotify Integration — Music control via Spotipy
"""
import os
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

try:
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth
    SPOTIPY_AVAILABLE = True
except ImportError:
    SPOTIPY_AVAILABLE = False
    logger.warning("spotipy not installed - Spotify integration disabled")

CACHE_PATH = Path(__file__).parent.parent.parent / "config" / "spotify_token.json"


class SpotifyBridge:
    """Spotify API bridge"""

    def __init__(self):
        self.client_id = os.getenv('SPOTIPY_CLIENT_ID')
        self.client_secret = os.getenv('SPOTIPY_CLIENT_SECRET')
        self.redirect_uri = os.getenv('SPOTIPY_REDIRECT_URI', 'http://localhost:8888/callback')
        self.sp = None

        if self.client_id and self.client_secret and SPOTIPY_AVAILABLE:
            self._connect()

    def _connect(self):
        """Connect to Spotify"""
        try:
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

            auth_manager = SpotifyOAuth(
                client_id=self.client_id,
                client_secret=self.client_secret,
                redirect_uri=self.redirect_uri,
                scope="user-read-playback-state user-modify-playback-state user-read-currently-playing",
                cache_path=str(CACHE_PATH)
            )

            self.sp = spotipy.Spotify(auth_manager=auth_manager)
            logger.info("Connected to Spotify")

        except Exception as e:
            logger.error(f"Failed to connect to Spotify: {e}")

    def play(self, query: str) -> Dict[str, Any]:
        """Search and play a track/artist/playlist"""
        if not self.sp:
            return {"status": "error", "message": "Spotify not configured"}

        try:
            # Search for track
            results = self.sp.search(q=query, type='track', limit=1)

            if not results['tracks']['items']:
                return {"status": "error", "message": f"No results found for: {query}"}

            track = results['tracks']['items'][0]
            track_uri = track['uri']

            # Play the track
            self.sp.start_playback(uris=[track_uri])

            return {
                "status": "ok",
                "message": f"Playing: {track['name']} by {track['artists'][0]['name']}"
            }

        except Exception as e:
            logger.error(f"Failed to play track: {e}")
            return {"status": "error", "message": str(e)}

    def pause(self) -> Dict[str, Any]:
        """Pause playback"""
        if not self.sp:
            return {"status": "error", "message": "Spotify not configured"}

        try:
            self.sp.pause_playback()
            return {"status": "ok", "message": "Paused"}

        except Exception as e:
            logger.error(f"Failed to pause: {e}")
            return {"status": "error", "message": str(e)}

    def resume(self) -> Dict[str, Any]:
        """Resume playback"""
        if not self.sp:
            return {"status": "error", "message": "Spotify not configured"}

        try:
            self.sp.start_playback()
            return {"status": "ok", "message": "Resumed"}

        except Exception as e:
            logger.error(f"Failed to resume: {e}")
            return {"status": "error", "message": str(e)}

    def next_track(self) -> Dict[str, Any]:
        """Skip to next track"""
        if not self.sp:
            return {"status": "error", "message": "Spotify not configured"}

        try:
            self.sp.next_track()
            return {"status": "ok", "message": "Skipped to next track"}

        except Exception as e:
            logger.error(f"Failed to skip: {e}")
            return {"status": "error", "message": str(e)}

    def current_track(self) -> Dict[str, Any]:
        """Get currently playing track"""
        if not self.sp:
            return {"status": "error", "message": "Spotify not configured"}

        try:
            current = self.sp.current_playback()

            if not current or not current.get('item'):
                return {"status": "ok", "message": "Nothing playing", "track": None}

            track = current['item']

            return {
                "status": "ok",
                "track": {
                    "name": track['name'],
                    "artist": track['artists'][0]['name'],
                    "album": track['album']['name'],
                    "is_playing": current['is_playing']
                }
            }

        except Exception as e:
            logger.error(f"Failed to get current track: {e}")
            return {"status": "error", "message": str(e)}

    def set_volume(self, level: int) -> Dict[str, Any]:
        """Set volume (0-100)"""
        if not self.sp:
            return {"status": "error", "message": "Spotify not configured"}

        try:
            level = max(0, min(100, level))
            self.sp.volume(level)
            return {"status": "ok", "message": f"Volume set to {level}%"}

        except Exception as e:
            logger.error(f"Failed to set volume: {e}")
            return {"status": "error", "message": str(e)}

    def get_devices(self) -> Dict[str, Any]:
        """Get available Spotify Connect devices"""
        if not self.sp:
            return {"status": "error", "message": "Spotify not configured", "devices": []}

        try:
            devices = self.sp.devices()

            device_list = [
                {
                    "name": dev['name'],
                    "type": dev['type'],
                    "is_active": dev['is_active']
                }
                for dev in devices.get('devices', [])
            ]

            return {"status": "ok", "devices": device_list}

        except Exception as e:
            logger.error(f"Failed to get devices: {e}")
            return {"status": "error", "message": str(e), "devices": []}


# Global instance
_spotify: Optional[SpotifyBridge] = None


def get_spotify() -> SpotifyBridge:
    """Get or create the global Spotify bridge"""
    global _spotify
    if _spotify is None:
        _spotify = SpotifyBridge()
    return _spotify
