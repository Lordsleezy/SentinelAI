"""
workers/identity/adb_handler.py
Reads SMS messages from Android phone via ADB for SMS 2FA.
Phone must be connected via USB with USB debugging enabled.
"""
from __future__ import annotations

import logging
import re
import subprocess
import time
from typing import Optional

logger = logging.getLogger(__name__)


class ADBHandler:
    """
    Reads SMS messages from Android phone via ADB.
    Phone must be connected via USB with:
    - USB debugging enabled
    - ADB authorized on the device
    """

    def is_available(self) -> bool:
        """Check if ADB is installed and a device is connected."""
        try:
            result = subprocess.run(
                ["adb", "devices"],
                capture_output=True, text=True, timeout=5
            )
            lines = result.stdout.strip().splitlines()
            # First line is "List of devices attached", rest are devices
            devices = [l for l in lines[1:] if l.strip() and "device" in l]
            return len(devices) > 0
        except FileNotFoundError:
            logger.debug("[ADB] adb command not found")
            return False
        except Exception as e:
            logger.debug("[ADB] is_available check failed: %s", e)
            return False

    def get_recent_sms(self, count: int = 10) -> list:
        """
        Read recent SMS messages via ADB shell.
        Returns list of {address, body, date, _id} dicts.
        """
        try:
            result = subprocess.run(
                ["adb", "shell", "content", "query",
                 "--uri", "content://sms/inbox",
                 "--projection", "_id:address:body:date"],
                capture_output=True, text=True, timeout=10
            )
            return self._parse_sms_output(result.stdout)[:count]
        except Exception as e:
            logger.debug("[ADB] get_recent_sms failed: %s", e)
            return []

    def _get_sms_ids(self) -> list:
        """Get list of current SMS IDs."""
        sms = self.get_recent_sms(50)
        return [s.get("_id", "") for s in sms]

    def _get_sms_by_id(self, sms_id: str) -> dict:
        """Get a specific SMS by ID."""
        try:
            result = subprocess.run(
                ["adb", "shell", "content", "query",
                 "--uri", f"content://sms/inbox",
                 "--where", f"_id={sms_id}",
                 "--projection", "_id:address:body:date"],
                capture_output=True, text=True, timeout=10
            )
            items = self._parse_sms_output(result.stdout)
            return items[0] if items else {}
        except Exception:
            return {}

    def _parse_sms_output(self, output: str) -> list:
        """Parse ADB content query output into list of dicts."""
        items = []
        for row in output.strip().split("Row:"):
            row = row.strip()
            if not row:
                continue
            item = {}
            for part in re.split(r",\s*(?=\w+=)", row):
                m = re.match(r"(\w+)=(.+)", part.strip())
                if m:
                    item[m.group(1)] = m.group(2)
            if item:
                items.append(item)
        return items

    def wait_for_sms_code(self, timeout: int = 60) -> Optional[str]:
        """
        Poll for new SMS containing a verification code.
        Checks every 3 seconds for up to timeout seconds.
        Returns 6-8 digit code or None if timeout exceeded.
        """
        if not self.is_available():
            logger.warning("[ADB] No device available for SMS 2FA")
            return None

        seen_ids = set(self._get_sms_ids())
        start = time.time()
        logger.info("[ADB] Waiting for SMS 2FA code (timeout=%ds)", timeout)

        while time.time() - start < timeout:
            time.sleep(3)
            current_ids = set(self._get_sms_ids())
            new_ids = current_ids - seen_ids

            for sms_id in new_ids:
                sms = self._get_sms_by_id(sms_id)
                body = sms.get("body", "")
                code = self._extract_code(body)
                if code:
                    logger.info("[ADB] SMS 2FA code found: %s", code)
                    return code

            seen_ids = current_ids

        logger.warning("[ADB] SMS 2FA timeout after %ds", timeout)
        return None

    def _extract_code(self, text: str) -> Optional[str]:
        """Extract 6-8 digit verification code from SMS text."""
        match = re.search(r"\b(\d{6,8})\b", text)
        return match.group(1) if match else None
