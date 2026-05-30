"""
Home Assistant Bridge — Full smart home control
"""
import os
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    logger.warning("httpx not available - Home Assistant integration disabled")


class HomeAssistantBridge:
    """Home Assistant API bridge"""

    def __init__(self):
        self.ha_url = os.getenv('HA_URL', 'http://homeassistant.local:8123')
        self.ha_token = os.getenv('HA_TOKEN')
        self.connected = False

        if self.ha_token and HTTPX_AVAILABLE:
            self._test_connection()

    def _test_connection(self):
        """Test connection to Home Assistant"""
        try:
            with httpx.Client() as client:
                response = client.get(
                    f"{self.ha_url}/api/",
                    headers={"Authorization": f"Bearer {self.ha_token}"},
                    timeout=5.0
                )
                if response.status_code == 200:
                    self.connected = True
                    logger.info("Connected to Home Assistant")
        except Exception as e:
            logger.warning(f"Home Assistant not reachable: {e}")

    def get_all_states(self) -> List[Dict[str, Any]]:
        """Get all entity states"""
        if not self.connected or not HTTPX_AVAILABLE:
            return []

        try:
            with httpx.Client() as client:
                response = client.get(
                    f"{self.ha_url}/api/states",
                    headers={"Authorization": f"Bearer {self.ha_token}"},
                    timeout=10.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to get states: {e}")
            return []

    def get_state(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Get single entity state"""
        if not self.connected or not HTTPX_AVAILABLE:
            return None

        try:
            with httpx.Client() as client:
                response = client.get(
                    f"{self.ha_url}/api/states/{entity_id}",
                    headers={"Authorization": f"Bearer {self.ha_token}"},
                    timeout=5.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to get state for {entity_id}: {e}")
            return None

    def call_service(self, domain: str, service: str, entity_id: str = None, **kwargs) -> bool:
        """Call a Home Assistant service"""
        if not self.connected or not HTTPX_AVAILABLE:
            return False

        try:
            data = kwargs.copy()
            if entity_id:
                data['entity_id'] = entity_id

            with httpx.Client() as client:
                response = client.post(
                    f"{self.ha_url}/api/services/{domain}/{service}",
                    headers={"Authorization": f"Bearer {self.ha_token}"},
                    json=data,
                    timeout=10.0
                )
                response.raise_for_status()
                return True
        except Exception as e:
            logger.error(f"Failed to call service {domain}.{service}: {e}")
            return False

    def turn_on(self, entity_id: str, **kwargs) -> bool:
        """Turn on an entity"""
        return self.call_service('homeassistant', 'turn_on', entity_id, **kwargs)

    def turn_off(self, entity_id: str) -> bool:
        """Turn off an entity"""
        return self.call_service('homeassistant', 'turn_off', entity_id)

    def set_temperature(self, entity_id: str, temperature: float) -> bool:
        """Set climate temperature"""
        return self.call_service('climate', 'set_temperature', entity_id, temperature=temperature)

    def get_camera_snapshot(self, entity_id: str) -> Optional[bytes]:
        """Get camera snapshot image"""
        if not self.connected or not HTTPX_AVAILABLE:
            return None

        try:
            with httpx.Client() as client:
                response = client.get(
                    f"{self.ha_url}/api/camera_proxy/{entity_id}",
                    headers={"Authorization": f"Bearer {self.ha_token}"},
                    timeout=15.0
                )
                response.raise_for_status()
                return response.content
        except Exception as e:
            logger.error(f"Failed to get camera snapshot: {e}")
            return None

    def describe_camera(self, entity_id: str, camera_name: str) -> str:
        """Get camera snapshot and describe with vision model"""
        snapshot = self.get_camera_snapshot(entity_id)

        if not snapshot:
            return f"Failed to get snapshot from {camera_name}"

        # Send to Ollama vision model (llava)
        try:
            import base64

            b64_image = base64.b64encode(snapshot).decode('utf-8')

            ollama_host = os.getenv('OLLAMA_HOST', 'http://127.0.0.1:11434')

            with httpx.Client() as client:
                response = client.post(
                    f"{ollama_host}/api/generate",
                    json={
                        "model": "llava",
                        "prompt": "Describe what you see in this image. Focus on any people, vehicles, packages, or notable activity.",
                        "images": [b64_image],
                        "stream": False
                    },
                    timeout=30.0
                )

                if response.status_code == 200:
                    data = response.json()
                    description = data.get('response', 'No description available').strip()
                    return f"{camera_name}: {description}"
                else:
                    return f"{camera_name}: Vision model unavailable"

        except Exception as e:
            logger.error(f"Failed to describe camera image: {e}")
            return f"{camera_name}: Description failed"

    def get_lights(self) -> List[Dict[str, Any]]:
        """Get all light entities"""
        states = self.get_all_states()
        return [s for s in states if s.get('entity_id', '').startswith('light.')]

    def get_cameras(self) -> List[Dict[str, Any]]:
        """Get all camera entities"""
        states = self.get_all_states()
        return [s for s in states if s.get('entity_id', '').startswith('camera.')]

    def get_locks(self) -> List[Dict[str, Any]]:
        """Get all lock entities"""
        states = self.get_all_states()
        return [s for s in states if s.get('entity_id', '').startswith('lock.')]

    def get_climate(self) -> List[Dict[str, Any]]:
        """Get all climate entities"""
        states = self.get_all_states()
        return [s for s in states if s.get('entity_id', '').startswith('climate.')]

    def lock(self, entity_id: str) -> bool:
        """Lock a lock"""
        return self.call_service('lock', 'lock', entity_id)

    def unlock(self, entity_id: str) -> bool:
        """Unlock a lock"""
        return self.call_service('lock', 'unlock', entity_id)

    def run_script(self, script_id: str) -> bool:
        """Run a Home Assistant script"""
        return self.call_service('script', 'turn_on', script_id)

    def fire_event(self, event_type: str, event_data: Dict[str, Any] = None) -> bool:
        """Fire a custom event"""
        if not self.connected or not HTTPX_AVAILABLE:
            return False

        try:
            with httpx.Client() as client:
                response = client.post(
                    f"{self.ha_url}/api/events/{event_type}",
                    headers={"Authorization": f"Bearer {self.ha_token}"},
                    json=event_data or {},
                    timeout=5.0
                )
                response.raise_for_status()
                return True
        except Exception as e:
            logger.error(f"Failed to fire event: {e}")
            return False

    def natural_language_command(self, command: str) -> Dict[str, Any]:
        """Execute a natural language home command"""
        cmd_lower = command.lower()

        # Turn off all lights
        if 'turn off' in cmd_lower and 'light' in cmd_lower and 'all' in cmd_lower:
            lights = self.get_lights()
            success_count = 0
            for light in lights:
                if self.turn_off(light['entity_id']):
                    success_count += 1

            return {
                "status": "ok",
                "message": f"Turned off {success_count} lights"
            }

        # Turn on all lights
        elif 'turn on' in cmd_lower and 'light' in cmd_lower and 'all' in cmd_lower:
            lights = self.get_lights()
            success_count = 0
            for light in lights:
                if self.turn_on(light['entity_id']):
                    success_count += 1

            return {
                "status": "ok",
                "message": f"Turned on {success_count} lights"
            }

        # Lock front door (fuzzy match)
        elif 'lock' in cmd_lower and ('front' in cmd_lower or 'door' in cmd_lower):
            locks = self.get_locks()
            front_lock = next((l for l in locks if 'front' in l['entity_id'].lower()), None)

            if front_lock:
                if self.lock(front_lock['entity_id']):
                    return {"status": "ok", "message": "Front door locked"}
                else:
                    return {"status": "error", "message": "Failed to lock front door"}
            else:
                return {"status": "error", "message": "Front door lock not found"}

        # Unlock
        elif 'unlock' in cmd_lower and ('front' in cmd_lower or 'door' in cmd_lower):
            locks = self.get_locks()
            front_lock = next((l for l in locks if 'front' in l['entity_id'].lower()), None)

            if front_lock:
                if self.unlock(front_lock['entity_id']):
                    return {"status": "ok", "message": "Front door unlocked"}
                else:
                    return {"status": "error", "message": "Failed to unlock front door"}
            else:
                return {"status": "error", "message": "Front door lock not found"}

        else:
            return {
                "status": "error",
                "message": f"Don't know how to: {command}"
            }


# Global instance
_ha_bridge: Optional[HomeAssistantBridge] = None


def get_ha_bridge() -> HomeAssistantBridge:
    """Get or create the global Home Assistant bridge"""
    global _ha_bridge
    if _ha_bridge is None:
        _ha_bridge = HomeAssistantBridge()
    return _ha_bridge
