"""
Package Tracking — USPS and other carriers
"""
import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

PACKAGES_FILE = Path(__file__).parent.parent.parent / "memory" / "vault" / "packages.json"


def _load_packages() -> List[Dict[str, Any]]:
    """Load packages from JSON file"""
    if not PACKAGES_FILE.exists():
        return []

    try:
        return json.loads(PACKAGES_FILE.read_text(encoding='utf-8'))
    except Exception as e:
        logger.error(f"Failed to load packages: {e}")
        return []


def _save_packages(packages: List[Dict[str, Any]]):
    """Save packages to JSON file"""
    try:
        PACKAGES_FILE.parent.mkdir(parents=True, exist_ok=True)
        PACKAGES_FILE.write_text(json.dumps(packages, indent=2), encoding='utf-8')
    except Exception as e:
        logger.error(f"Failed to save packages: {e}")


def add_package(tracking_number: str, carrier: str, description: str = "") -> Dict[str, Any]:
    """Add a package to track"""
    packages = _load_packages()

    package = {
        "tracking_number": tracking_number,
        "carrier": carrier.lower(),
        "description": description,
        "added_at": datetime.now().isoformat(),
        "last_check": None,
        "last_status": "Unknown",
        "delivered": False
    }

    packages.append(package)
    _save_packages(packages)

    return {
        "status": "ok",
        "message": f"Package {tracking_number} added",
        "package": package
    }


def get_package_status(tracking_number: str, carrier: str) -> Dict[str, Any]:
    """Get status of a specific package"""
    carrier = carrier.lower()

    if carrier == "usps":
        return _usps_status(tracking_number)
    elif carrier == "ups":
        return {"status": "error", "message": "UPS tracking not yet configured - coming soon"}
    elif carrier == "fedex":
        return {"status": "error", "message": "FedEx tracking not yet configured - coming soon"}
    elif carrier == "amazon":
        return {"status": "error", "message": "Amazon tracking not yet configured - coming soon"}
    else:
        return {"status": "error", "message": f"Unknown carrier: {carrier}"}


def _usps_status(tracking_number: str) -> Dict[str, Any]:
    """Get USPS tracking status"""
    usps_user_id = os.getenv('USPS_USER_ID')

    if not usps_user_id:
        return {
            "status": "error",
            "message": "USPS_USER_ID not configured",
            "tracking_status": "Unknown"
        }

    # TODO: Implement USPS Web Tools API integration
    # For now, return a placeholder
    return {
        "status": "ok",
        "tracking_status": "In Transit",
        "last_update": datetime.now().isoformat(),
        "message": "USPS API integration coming soon - this is a placeholder"
    }


def get_all_packages() -> List[Dict[str, Any]]:
    """Get all tracked packages"""
    return _load_packages()


def check_deliveries() -> Dict[str, Any]:
    """Check all packages for status changes"""
    packages = _load_packages()
    changes = []

    for package in packages:
        if package.get('delivered'):
            continue

        tracking_number = package['tracking_number']
        carrier = package['carrier']

        status = get_package_status(tracking_number, carrier)

        if status.get('status') == 'ok':
            new_status = status.get('tracking_status', 'Unknown')

            if new_status != package.get('last_status'):
                changes.append({
                    "tracking_number": tracking_number,
                    "carrier": carrier,
                    "description": package.get('description', ''),
                    "old_status": package.get('last_status'),
                    "new_status": new_status
                })

                package['last_status'] = new_status
                package['last_check'] = datetime.now().isoformat()

                if 'delivered' in new_status.lower():
                    package['delivered'] = True

    _save_packages(packages)

    return {
        "status": "ok",
        "changes": changes,
        "message": f"Checked {len(packages)} packages, {len(changes)} status changes"
    }
