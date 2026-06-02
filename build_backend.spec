# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for SentinelAI Python backend.

Bundles the Flask backend, all worker modules, and the integrations that
ship in this build into ``dist/sentinel_backend/sentinel_backend.exe``.

Optional integrations (telethon, openwakeword, whisper, selenium, openai,
prometheus_client, etc.) are loaded lazily by their workers and protected
by try/except, so they intentionally are NOT in hiddenimports — keeping
them out lets PyInstaller succeed even when those packages are absent
from the build environment.
"""
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# Pull in submodule trees for the heavy ML / data packages that PyInstaller's
# static analyzer can miss. Each call is guarded so a missing optional package
# does not crash the build.
def _safe_submodules(name: str):
    try:
        return collect_submodules(name)
    except Exception:
        return []


def _safe_data(name: str):
    try:
        return collect_data_files(name)
    except Exception:
        return []


hidden_chromadb = _safe_submodules('chromadb')
hidden_sentence_transformers = _safe_submodules('sentence_transformers')
hidden_transformers = _safe_submodules('transformers')
hidden_anthropic = _safe_submodules('anthropic')
hidden_langgraph = _safe_submodules('langgraph')
hidden_crewai = _safe_submodules('crewai')

data_chromadb = _safe_data('chromadb')
data_sentence_transformers = _safe_data('sentence_transformers')


a = Analysis(
    ['desktop_app.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('memory', 'memory'),
        ('config', 'config'),
        ('templates', 'templates'),
        ('static', 'static'),
        ('.env.example', '.'),
        ('capability_registry.json', '.'),
        ('installer_assets/guardian_core', 'installer_assets/guardian_core'),
        ('tools/httpx', 'tools/httpx'),
        ('tools/subfinder', 'tools/subfinder'),
        ('tools/katana', 'tools/katana'),
        ('tools/nuclei', 'tools/nuclei'),
        ('tools/godot', 'tools/godot'),
        ('installer_assets/godot_runtime', 'installer_assets/godot_runtime'),
    ] + data_chromadb + data_sentence_transformers,
    hiddenimports=[
        # Orchestration pipeline
        'workers.orchestration',
        'workers.orchestration.task_decomposer',
        'workers.orchestration.confidence',
        'workers.orchestration.verifier',
        'workers.orchestration.chain_of_thought',
        'workers.orchestration.rag',
        'workers.orchestration.model_selector',
        'workers.orchestration.structured_output',
        'workers.orchestration.pipeline',

        # Licensing
        'workers.licensing',
        'workers.licensing.license_manager',

        # Capability system (minimal stubs that exist in this repo)
        'workers.capability',
        'workers.capability.registry',
        'workers.capability.gap_detector',
        'workers.capability.capability_finder',
        'workers.capability.capability_installer',
        'workers.capability.capability_builder',

        # OpenClaw workers
        'workers.openclaw',
        'workers.openclaw.calendar',
        'workers.openclaw.contacts',
        'workers.openclaw.reminders',
        'workers.openclaw.notes',
        'workers.openclaw.web',
        'workers.openclaw.openclaw_worker',

        # Voice & Messaging
        'workers.voice',
        'workers.voice.wake_word',
        'workers.messaging',
        'workers.messaging.telegram_bridge',
        'workers.messaging.whatsapp_bridge',

        # Smart Home
        'workers.home',
        'workers.home.home_assistant',
        'workers.home.camera_worker',

        # Background workers
        'workers.proactive',
        'workers.proactive.scheduler',
        'workers.health',
        'workers.health.wearables',
        'workers.finance',
        'workers.finance.firefly',
        'workers.entertainment',
        'workers.entertainment.spotify',
        'workers.logistics',
        'workers.logistics.package_tracker',
        'workers.news',
        'workers.news.miniflux_reader',

        # Earn (stubs)
        'workers.earn',
        'workers.earn.sources',
        'workers.earn.sources.bounty_targets',
        'workers.earn.sources.remoteok_scanner',
        'workers.earn.sources.freelancer_scanner',
        'workers.earn.sources.upwork_scanner',

        # Market (stubs, dry_run only)
        'market',
        'market.openbb_bridge',
        'market.freqtrade_manager',

        # Core root modules
        'memory_manager',
        'db',
        'learning_memory',
        'queue_manager',
        'worker_manager',
        'watchdog',
        'health_monitor',
        'orchestration',
        'internet_runtime',
        'model_router',
        'reflection',
        'tool_registry',
        'tools.registry',
        'executor',
        'scanner',
        'openclaw_integration',
        'workers.forge_worker',
        'workers.guardian.bundled_toolchain',
        'workers.guardian.guardian_bootstrap',
        'builders.runtime.godot_runtime',
        'builders.builder_status',
        'workers.guardian.tools.tool_registry',
        'notifications',

        # Flask & web
        'flask',
        'flask_cors',
        'flask_socketio',
        'engineio.async_drivers.threading',

        # Async / scheduling
        'apscheduler',
        'apscheduler.schedulers.background',
        'apscheduler.triggers.cron',
        'apscheduler.triggers.interval',

        # HTTP / parsing
        'httpx',
        'requests',
        'bs4',
        'lxml',
        'feedparser',
        'yaml',

        # System tray + imaging
        'pystray',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',

        # System monitoring
        'psutil',
    ] + hidden_chromadb + hidden_sentence_transformers + hidden_transformers
       + hidden_anthropic + hidden_langgraph + hidden_crewai,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'PyQt5',
        'PyQt6',
        'PySide6',
        'IPython',
        'jupyter',
        'pytest',
        'setuptools._distutils',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='sentinel_backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='sentinel_backend',
)
