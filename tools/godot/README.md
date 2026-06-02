# Bundled Godot runtime

Godot Engine for GAME builds is installed here as `Godot*.exe` by:

- Sentinel installer / `installer_assets/godot_runtime/`
- Startup bootstrap (`builders/runtime/godot_runtime.py`)
- **Install** in the launch dialog (downloads from GitHub releases)
- **Browse** to register an existing `Godot.exe`

Priority: this folder → saved path in `memory/vault/builder_runtime.json` → `C:\Tools\` → PATH.
