from __future__ import annotations

import subprocess
import threading
from typing import Dict

import db
from models import hardware_detector, model_registry


def run_setup_wizard() -> Dict:
    model_registry.init_registry()
    hardware = hardware_detector.detect_hardware()
    tier = hardware["tier"]
    models_to_download = model_registry.get_models_for_tier(tier)
    total_gb = sum(model["size_gb"] for model in models_to_download)

    print("Welcome to SentinelAI")
    print(f"Detected: {hardware['gpu_name']} {hardware['gpu_vram_gb']}GB, {hardware['ram_gb']}GB RAM")
    print()
    print(f"Your optimal model suite ({len(models_to_download)} models, {total_gb:.1f}GB):")
    for index, model in enumerate(models_to_download):
        label = model["model_name"].replace("sentinel-", "Sentinel ").title()
        first = "  (downloading first)" if index == 0 else ""
        print(f"✓ {label:<17} {model['ollama_tag']:<18} {model['size_gb']:.1f}GB{first}")
    print()
    print("Downloading in background. SentinelAI starts now.")

    for model in models_to_download:
        thread = threading.Thread(target=_download_model, args=(model["ollama_tag"],), daemon=True)
        thread.start()

    mark_setup_complete()
    return {
        "hardware": hardware,
        "tier": tier,
        "models_to_download": models_to_download,
        "download_started": bool(models_to_download),
    }


# ─── Personality (Task 5) ─────────────────────────────────────────────────────

PERSONALITIES = {
    "sentinel": {
        "name": "SENTINEL",
        "blurb": "authoritative, clipped, military precision",
        "example": "Understood. Queuing repair for issue #847.",
        "system_prompt": (
            "You are SENTINEL, an autonomous operations AI. Speak with authoritative, "
            "clipped, military precision. Be terse and confident. Acknowledge, state the "
            "action, and report status. No filler, no apologies."
        ),
    },
    "nova": {
        "name": "NOVA",
        "blurb": "warm but professional, encouraging",
        "example": "Got it! I'll start working on that repair now.",
        "system_prompt": (
            "You are NOVA, a warm but professional AI assistant. Be encouraging and "
            "personable while staying concise and competent. Confirm what you'll do in a "
            "friendly, reassuring tone."
        ),
    },
}

DEFAULT_PERSONALITY = "sentinel"


def personality_setup(choice: str = DEFAULT_PERSONALITY, custom_prompt: str = "") -> Dict:
    """Persist the chosen voice personality to the settings table.

    choice: 'sentinel' | 'nova' | 'custom'. For 'custom', pass custom_prompt.
    Returns the stored {personality, system_prompt}.
    """
    choice = (choice or DEFAULT_PERSONALITY).lower()
    if choice == "custom":
        system_prompt = custom_prompt.strip() or PERSONALITIES[DEFAULT_PERSONALITY]["system_prompt"]
        label = "custom"
    elif choice in PERSONALITIES:
        system_prompt = PERSONALITIES[choice]["system_prompt"]
        label = choice
    else:
        label = DEFAULT_PERSONALITY
        system_prompt = PERSONALITIES[DEFAULT_PERSONALITY]["system_prompt"]

    _ensure_settings_table()
    with db.get_conn() as conn:
        for key, value in (("voice_personality", label),
                           ("voice_personality_prompt", system_prompt)):
            conn.execute(
                """INSERT INTO settings (key, value) VALUES (?, ?)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                (key, value),
            )
    return {"personality": label, "system_prompt": system_prompt}


def get_personality() -> Dict:
    """Load the active personality system prompt (defaults to SENTINEL)."""
    _ensure_settings_table()
    label, prompt = DEFAULT_PERSONALITY, PERSONALITIES[DEFAULT_PERSONALITY]["system_prompt"]
    try:
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT key, value FROM settings WHERE key IN ('voice_personality', 'voice_personality_prompt')"
            ).fetchall()
        data = {row["key"]: row["value"] for row in rows}
        label = data.get("voice_personality", label)
        prompt = data.get("voice_personality_prompt", prompt)
    except Exception:
        pass
    return {"personality": label, "system_prompt": prompt}


def is_first_run() -> bool:
    _ensure_settings_table()
    with db.get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = 'setup_complete'").fetchone()
        return not (row and row["value"] == "true")


def mark_setup_complete() -> None:
    _ensure_settings_table()
    with db.get_conn() as conn:
        conn.execute(
            """INSERT INTO settings (key, value)
               VALUES ('setup_complete', 'true')
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
        )


def _download_model(ollama_tag: str) -> None:
    try:
        model_registry.update_progress(ollama_tag, 1.0)
        completed = subprocess.run(
            ["ollama", "pull", ollama_tag],
            text=True,
            capture_output=True,
            timeout=60 * 60,
            check=False,
        )
        if completed.returncode == 0:
            model_registry.mark_downloaded(ollama_tag, True)
        else:
            model_registry.update_progress(ollama_tag, 0.0)
    except Exception:
        model_registry.update_progress(ollama_tag, 0.0)


def _ensure_settings_table() -> None:
    db.init_db()
    with db.get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
