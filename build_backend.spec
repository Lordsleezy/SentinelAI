# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for SentinelAI Python backend
Bundles all workers, dependencies, and config into sentinel_backend executable
"""
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

a = Analysis(
    ['desktop_app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('memory/vault', 'memory/vault'),
        ('config', 'config'),
        ('.env.example', '.'),
        ('workers', 'workers'),
        ('market', 'market'),
        ('capability_registry.json', '.'),
        ('BUILD_SYSTEM_ROADMAP.md', '.'),
        ('README.md', '.'),
    ],
    hiddenimports=[
        # Orchestration
        'workers.orchestration.task_decomposer',
        'workers.orchestration.confidence',
        'workers.orchestration.verifier',
        'workers.orchestration.chain_of_thought',
        'workers.orchestration.rag',
        'workers.orchestration.model_selector',
        'workers.orchestration.structured_output',
        'workers.orchestration.pipeline',

        # Licensing
        'workers.licensing.license_manager',

        # Capability system
        'workers.capability.registry',
        'workers.capability.gap_detector',
        'workers.capability.capability_finder',
        'workers.capability.capability_installer',
        'workers.capability.capability_builder',

        # OpenClaw workers
        'workers.openclaw.calendar',
        'workers.openclaw.contacts',
        'workers.openclaw.reminders',
        'workers.openclaw.notes',
        'workers.openclaw.web',
        'workers.openclaw.openclaw_worker',

        # Voice & Messaging
        'workers.voice.wake_word',
        'workers.messaging.telegram_bridge',
        'workers.messaging.whatsapp_bridge',

        # Smart Home
        'workers.home.home_assistant',
        'workers.home.camera_worker',

        # Background workers
        'workers.proactive.scheduler',
        'workers.health.wearables',
        'workers.finance.firefly',
        'workers.entertainment.spotify',
        'workers.logistics.package_tracker',
        'workers.news.miniflux_reader',

        # Earn
        'workers.earn.sources.bounty_targets',
        'workers.earn.sources.remoteok_scanner',
        'workers.earn.sources.freelancer_scanner',
        'workers.earn.sources.upwork_scanner',

        # Market
        'market.openbb_bridge',
        'market.freqtrade_manager',

        # Core modules
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

        # AI & ML
        'anthropic',
        'chromadb',
        'sentence_transformers',
        'openai',
        'ollama',

        # Data & Storage
        'sqlalchemy',
        'sqlalchemy.orm',
        'sqlalchemy.dialects.sqlite',

        # Async & Scheduling
        'apscheduler',
        'apscheduler.schedulers.background',
        'apscheduler.triggers.cron',

        # Monitoring
        'prometheus_client',

        # Calendar & Events
        'gcsa',
        'gcsa.event',

        # Smart Home
        'blinkpy',
        'blinkpy.auth',
        'blinkpy.sync',

        # Music
        'spotipy',
        'spotipy.client',

        # Messaging
        'telethon',
        'telethon.client',
        'telethon.sessions',

        # Voice
        'openwakeword',
        'openwakeword.model',
        'whisper',
        'whisper.audio',

        # News
        'feedparser',

        # Additional
        'pystray',
        'PIL',
        'httpx',
        'requests',
        'beautifulsoup4',
        'selenium',
        'playwright',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludedimports=[],
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
    upx=True,
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
    upx=True,
    upx_exclude=[],
    name='sentinel_backend',
)
