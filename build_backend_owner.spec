# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — OWNER build.

Includes everything from the consumer spec PLUS:
  - workers.earn and all earn sub-modules
  - SENTINEL_OWNER_MODE baked to 'true'
  - Output name: sentinel_backend (same binary name, different dist folder)

WARNING: This build MUST NOT be publicly distributed.
"""
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

def _safe_submodules(name):
    try:
        return collect_submodules(name)
    except Exception:
        return []

def _safe_data(name):
    try:
        return collect_data_files(name)
    except Exception:
        return []

hidden_chromadb              = _safe_submodules('chromadb')
hidden_sentence_transformers = _safe_submodules('sentence_transformers')
hidden_transformers          = _safe_submodules('transformers')
hidden_anthropic             = _safe_submodules('anthropic')
hidden_langgraph             = _safe_submodules('langgraph')
hidden_crewai                = _safe_submodules('crewai')

data_chromadb              = _safe_data('chromadb')
data_sentence_transformers = _safe_data('sentence_transformers')

a = Analysis(
    ['desktop_app.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('memory',                  'memory'),
        ('config',                  'config'),
        ('templates',               'templates'),
        ('static',                  'static'),
        ('.env.example',            '.'),
        ('capability_registry.json', '.'),
        ('build_info.py',           '.'),
    ] + data_chromadb + data_sentence_transformers,
    hiddenimports=[
        # Orchestration
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
        'workers.licensing.trial_manager',
        'workers.licensing.killswitch_checker',

        # Telemetry
        'workers.telemetry',
        'workers.telemetry.telemetry_manager',

        # Capability
        'workers.capability',
        'workers.capability.registry',
        'workers.capability.gap_detector',
        'workers.capability.capability_finder',
        'workers.capability.capability_installer',
        'workers.capability.capability_builder',

        # OpenClaw
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

        # Background
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

        # Setup
        'workers.setup',
        'workers.setup.machine_scanner',

        # ── Owner-only: Earn workers ──
        'workers.earn',
        'workers.earn.sources',
        'workers.earn.sources.bounty_targets',
        'workers.earn.sources.remoteok_scanner',
        'workers.earn.sources.freelancer_scanner',
        'workers.earn.sources.upwork_scanner',

        # Market
        'market',
        'market.openbb_bridge',
        'market.freqtrade_manager',

        # Core root
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
        'notifications',

        # Flask & web
        'flask',
        'flask_cors',
        'flask_socketio',
        'engineio.async_drivers.threading',

        # Scheduling
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

        # System tray
        'pystray',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',

        # Monitoring
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
    env={'SENTINEL_OWNER_MODE': 'true'},
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
