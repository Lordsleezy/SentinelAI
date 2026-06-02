# Preinstalled Dependencies

Target product experience: **Sentinel installer ships everything officially supported.**

## Tier 1 (Required — always present)

- Python, venv, SQLite, Git
- Node.js, npm
- Guardian core: httpx, subfinder, katana, nuclei
- Ollama (AI)

## Tier 2 (Recommended — first launch)

- Godot (`tools/godot/` or background `bootstrap_godot_runtime`)
- Playwright, Electron tooling
- Extended Guardian: dnsx, naabu, ffuf, amass, ZAP, …

## Tier 3 (On demand)

- Android SDK / Gradle / JDK
- Unity, Unreal, VR modules
- Large optional model packs

## Repo bundles today

- `tools/godot/Godot_*` — Godot win64 (nested folder supported via `rglob`)
- Guardian binaries under project `tools/` paths (see `workers/guardian/bundled_toolchain`)

## Validation

Run `python run_capability_validation.py` for registry, Godot probe, and forge stage smoke checks.
