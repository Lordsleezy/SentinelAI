"""
Camera Worker — Multi-brand camera support via Home Assistant
"""
import os
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

from .home_assistant import get_ha_bridge


def list_cameras() -> List[Dict[str, Any]]:
    """List all available cameras"""
    ha = get_ha_bridge()

    if ha.connected:
        cameras = ha.get_cameras()
        return [
            {
                'name': cam.get('attributes', {}).get('friendly_name', cam['entity_id']),
                'entity_id': cam['entity_id'],
                'state': cam.get('state')
            }
            for cam in cameras
        ]
    else:
        return []


def look_at(camera_name: str) -> Dict[str, Any]:
    """Snapshot a specific camera and describe what's visible"""
    ha = get_ha_bridge()

    if not ha.connected:
        return {
            "status": "error",
            "message": "Home Assistant not configured"
        }

    # Find camera by fuzzy name match
    cameras = ha.get_cameras()
    camera_name_lower = camera_name.lower()

    matched_camera = None
    for cam in cameras:
        friendly_name = cam.get('attributes', {}).get('friendly_name', '').lower()
        entity_id = cam['entity_id'].lower()

        if camera_name_lower in friendly_name or camera_name_lower in entity_id:
            matched_camera = cam
            break

    if not matched_camera:
        return {
            "status": "error",
            "message": f"Camera '{camera_name}' not found"
        }

    # Get description
    description = ha.describe_camera(
        matched_camera['entity_id'],
        matched_camera.get('attributes', {}).get('friendly_name', camera_name)
    )

    return {
        "status": "ok",
        "camera": matched_camera['entity_id'],
        "description": description
    }


def look_at_all() -> Dict[str, Any]:
    """Snapshot all cameras and describe what's visible"""
    ha = get_ha_bridge()

    if not ha.connected:
        return {
            "status": "error",
            "message": "Home Assistant not configured",
            "cameras": {}
        }

    cameras = ha.get_cameras()

    if not cameras:
        return {
            "status": "ok",
            "message": "No cameras found",
            "cameras": {}
        }

    results = {}

    for cam in cameras:
        friendly_name = cam.get('attributes', {}).get('friendly_name', cam['entity_id'])
        description = ha.describe_camera(cam['entity_id'], friendly_name)
        results[friendly_name] = description

    return {
        "status": "ok",
        "cameras": results
    }


# Direct brand fallbacks (if HA not configured) - stubs for now
def _blink_fallback():
    """Blink camera fallback (requires blinkpy)"""
    # TODO: Implement Blink direct integration
    return {"status": "error", "message": "Blink direct integration not yet implemented - use Home Assistant"}


def _eufy_fallback():
    """Eufy camera fallback (requires pyeufysecurity)"""
    # TODO: Implement Eufy direct integration
    return {"status": "error", "message": "Eufy direct integration not yet implemented - use Home Assistant"}


def _arlo_fallback():
    """Arlo camera fallback (requires pyarlo)"""
    # TODO: Implement Arlo direct integration
    return {"status": "error", "message": "Arlo direct integration not yet implemented - use Home Assistant"}
