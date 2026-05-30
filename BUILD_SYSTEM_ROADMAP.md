# SentinelAI Build System - Complete Roadmap

## Status: Orchestration Pipeline Complete (Tracks 1-25 ✅)

All 25 orchestration tracks are implemented and committed:
- ✅ Tracks 17-19: Decomposition, Confidence Escalation, Verification
- ✅ Tracks 20-25: CoT, RAG, Model Selection, Structured Output, Plan Approval UI, Full Pipeline

**Ready to begin build system implementation (Parts 1-7).**

---

## ✅ COMPLETED BUILD WORK

### **PART 1: Repository Cleanup** ✅
- ✅ Updated .gitignore to commit venv/ and node_modules/
- ✅ Added .gitkeep files to 10 empty directories
- ✅ Updated .env.example with ANTHROPIC_API_KEY
- ✅ Ready for distribution

### **PART 2: Setup Wizard** ✅
- ✅ Created 9-page Electron wizard (setup_wizard.html)
  - Welcome, GitHub, AI/APIs, Smart Home, Messaging, Finance, Entertainment, Wearables, Complete
- ✅ First-run detection in main.js
- ✅ IPC handler writes .env and launches main windows
- ✅ Ready for deployment

---

## 🚧 REMAINING BUILD WORK

### **PART 3: PyInstaller Backend Bundling**

**Goal:** Bundle Python backend + venv into single executable

**Files to create:**
- `build_backend.spec` — PyInstaller spec file
- `scripts/build_backend.bat` — Windows build script
- `scripts/build_backend.sh` — macOS/Linux build script (optional)

**Requirements:**
```bash
pip install pyinstaller
```

**Spec Configuration:**
```python
# build_backend.spec should:
- Include all of workers/, *.py modules
- Collect venv dependencies 
- Set entrypoint to desktop_app.py
- Binary name: sentinelai-backend.exe
- Output: build/backend_dist/
- Hidden imports: [
    'workers.*',
    'anthropic',
    'chromadb',
    'sentence_transformers',
    'flask',
    'flask_cors',
    'pystray',
    'PIL',
    'httpx',
    ... (add all external libs)
  ]
```

**Build Script:**
```batch
@echo off
cd /d %~dp0..
echo Building SentinelAI Python backend...
python -m PyInstaller build_backend.spec
if %errorlevel% neq 0 exit /b %errorlevel%
echo Backend build complete: build\backend_dist\
pause
```

**Output:** `sentinelai-backend.exe` (~150-300MB)

---

### **PART 4: Electron Builder Installer**

**Goal:** Create Windows installer with PyInstaller backend bundled

**Files to create/update:**
- `package.json` — Add electron-builder config
- `create_icon.js` — Generate icon.ico programmatically
- `scripts/build_installer.bat` — Master build script
- Optional: `electron-builder-config.json` — Detailed config

**package.json additions:**
```json
{
  "build": {
    "appId": "com.sentinelai.app",
    "productName": "SentinelAI",
    "directories": {
      "output": "installer_dist",
      "buildResources": "assets"
    },
    "files": [
      "desktop-shell/**",
      "*.py",
      "workers/**",
      "memory/**",
      "tools/**",
      "!node_modules/**",
      "!.venv/**",
      "!.git/**",
      "!.github/**"
    ],
    "win": {
      "target": ["nsis"],
      "icon": "desktop-shell/assets/icon.ico",
      "certificateFile": null,
      "certificatePassword": null,
      "signingHashAlgorithms": ["sha256"],
      "sign": null
    },
    "nsis": {
      "oneClick": false,
      "allowToChangeInstallationDirectory": true,
      "createDesktopShortcut": true,
      "createStartMenuShortcut": true,
      "shortcutName": "SentinelAI",
      "installerIcon": "desktop-shell/assets/icon.ico",
      "uninstallerIcon": "desktop-shell/assets/icon.ico",
      "installerHeaderIcon": "desktop-shell/assets/icon.ico"
    },
    "files": [
      "desktop-shell/**/*",
      "build/backend_dist/**/*",
      ".env.example",
      "README.md"
    ]
  }
}
```

**Icon Generation (create_icon.js):**
```javascript
// Programmatically create icon.ico from gradient + logo
// Output to: desktop-shell/assets/icon.ico
```

**Build Script:**
```batch
@echo off
echo Building SentinelAI Installer...

REM Step 1: Build backend
call scripts\build_backend.bat
if %errorlevel% neq 0 exit /b %errorlevel%

REM Step 2: Create icon
node create_icon.js
if %errorlevel% neq 0 exit /b %errorlevel%

REM Step 3: Build Electron installer
npm run electron-builder

echo Installer ready: installer_dist\SentinelAI Setup.exe
pause
```

**Output:** `SentinelAI Setup.exe` (~500MB-1GB depending on backend size)

**Installer Features:**
- Custom NSIS installer UI
- Python backend bundled
- Shortcuts created on desktop + Start Menu
- Single-file installation
- Uninstall support

---

### **PART 5: GitHub Actions CI/CD**

**Goal:** Auto-build and release on push/tags

**File to create:**
- `.github/workflows/build.yml`

**Workflow Configuration:**
```yaml
name: Build SentinelAI

on:
  push:
    branches: [master, main]
    tags: ['v*']
  workflow_dispatch:

jobs:
  build-windows:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      
      - name: Setup Node.js
        uses: actions/setup-node@v3
        with:
          node-version: '18'
      
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install pyinstaller
          npm install
      
      - name: Build backend
        run: python -m PyInstaller build_backend.spec
      
      - name: Create icon
        run: node create_icon.js
      
      - name: Build Electron installer
        run: npm run electron-builder
      
      - name: Upload artifact
        uses: actions/upload-artifact@v3
        with:
          name: sentinelai-installer
          path: installer_dist/SentinelAI*.exe
      
      - name: Create Release
        if: startsWith(github.ref, 'refs/tags/')
        uses: softprops/action-gh-release@v1
        with:
          files: installer_dist/SentinelAI*.exe
          draft: false
          prerelease: false
```

**Features:**
- Runs on Windows (required for exe building)
- Builds on push to master and tags
- Creates GitHub Release with installer attachment
- Artifacts available for download

---

### **PART 6: Self-Extending Capability System**

**Goal:** Runtime gap detection, tool search, installation, and Forge integration

**Files to create:**
- `workers/capability/registry.py` — Capability registry management
- `workers/capability/gap_detector.py` — Detect missing capabilities
- `workers/capability/capability_finder.py` — Search PyPI + GitHub
- `workers/capability/capability_installer.py` — Install and wrap tools
- `workers/capability/capability_builder.py` — Forge integration
- `capability_registry.json` — Registry of installed capabilities
- Update all workers with `CAPABILITY_DESCRIPTION`

**Gap Detector:**
```python
class GapDetector:
    def detect_gaps(task: str) -> List[str]:
        """Find capabilities needed but not available"""
        # Ask LLM what tools are needed
        # Check against registry
        # Return missing capability names
```

**Capability Finder:**
```python
class CapabilityFinder:
    def search_pypi(query: str) -> List[Package]:
        """Search PyPI for matching packages"""
    
    def search_github(query: str) -> List[Repo]:
        """Search GitHub for tool implementations"""
```

**Capability Installer:**
```python
class CapabilityInstaller:
    def install(package_name: str) -> bool:
        """
        1. pip install package
        2. Create worker wrapper
        3. Register in capability_registry.json
        4. Test functionality
        5. Enable in routing
        """
```

**Capability Builder (Forge Integration):**
```python
class CapabilityBuilder:
    def build_missing_tool(spec: ToolSpec) -> bool:
        """
        For tools not found on PyPI:
        1. Send spec to Forge
        2. Forge generates implementation
        3. Review for approval
        4. Install locally
        5. Register
        """
```

**Registry Format (capability_registry.json):**
```json
{
  "capabilities": {
    "web_search": {
      "provider": "brave",
      "status": "installed",
      "worker": "openclaw.web",
      "installed_date": "2026-05-29"
    },
    "image_generation": {
      "provider": "custom",
      "status": "available",
      "requires_approval": true,
      "worker": "tools.image_gen"
    }
  }
}
```

**Routes:**
- `POST /capability/detect-gaps` — Analyze task for missing capabilities
- `POST /capability/search` — Find tools (PyPI/GitHub)
- `POST /capability/install/{capability}` — Install tool
- `POST /capability/build/{capability}` — Request Forge build
- `GET /capability/status` — List installed capabilities
- `POST /capability/approve/{build_id}` — Approve Forge build
- `DELETE /capability/{name}` — Uninstall capability

**UI Integration:**
- Modal dialog for capability approval
- Shows package info + installer
- Can skip approval with "continue without"
- Shows installation progress

---

### **PART 7: Final Wiring & Release**

**Files to update:**
- `README.md` — Installation and quick-start guide
- `DEPLOYMENT.md` — Distribution documentation
- Version bump in `package.json`

**README Updates:**
- Installation from exe
- First-run setup wizard walkthrough
- Architecture overview
- Quick-start examples
- Troubleshooting

**DEPLOYMENT.md:**
- System requirements (Windows 10+, 4GB RAM, 5GB disk)
- Installation steps
- Uninstallation steps
- Configuration file location
- Logs location
- Backup/restore procedures
- Known issues and workarounds

**Final Commit:**
```bash
git tag v1.0.0-alpha
git push origin v1.0.0-alpha
# GitHub Actions auto-builds and creates release
```

---

## 📋 BUILD CHECKLIST

### Part 3: PyInstaller
- [ ] Create `build_backend.spec`
- [ ] Test spec on Windows
- [ ] Verify backend.exe runs standalone
- [ ] Commit spec

### Part 4: Electron Builder
- [ ] Update `package.json` with builder config
- [ ] Create icon generation script
- [ ] Create build_installer.bat
- [ ] Test installer on fresh Windows VM
- [ ] Verify shortcuts work
- [ ] Verify .env setup wizard triggers
- [ ] Commit

### Part 5: GitHub Actions
- [ ] Create `.github/workflows/build.yml`
- [ ] Test workflow on fork
- [ ] Verify artifact upload
- [ ] Verify release creation
- [ ] Commit

### Part 6: Capability System
- [ ] Create capability registry files
- [ ] Implement gap detector
- [ ] Implement PyPI/GitHub searcher
- [ ] Implement installer
- [ ] Implement Forge builder
- [ ] Create Flask routes
- [ ] Test end-to-end
- [ ] Commit

### Part 7: Final Polish
- [ ] Update README
- [ ] Create DEPLOYMENT.md
- [ ] Bump version numbers
- [ ] Test complete build pipeline
- [ ] Tag v1.0.0-alpha
- [ ] Verify auto-release

---

## 🚀 POST-BUILD DISTRIBUTION

**Installer Distribution:**
1. GitHub Releases page (SentinelAI-Setup.exe)
2. Create website/landing page
3. Optional: Distribute via Windows Package Manager
4. Optional: Submit to Microsoft Store

**Installation Time:** ~5-10 minutes (depending on internet/hardware)
**Disk Space Required:** ~5GB
**Launch Time:** ~3-5 seconds (after first run setup)

---

## 📊 FINAL STATS

**Codebase:**
- 25 orchestration tracks ✅
- 50+ Python workers
- Full Electron desktop shell
- RAG + Vector retrieval
- Model routing + confidence escalation
- Self-extending capability system
- **Total:** ~50,000 lines of code

**Distribution:**
- Single .exe installer
- No dependencies to install
- First-run wizard
- Auto-updating capability system
- Full CI/CD pipeline

**Architecture:**
- Python backend (Flask)
- Electron frontend (React + Three.js)
- SQLite + ChromaDB storage
- Ollama local AI + Claude API escalation
- 12+ integrated services

---

## ⏱️ ESTIMATED COMPLETION TIME

- Part 3 (PyInstaller): **2-3 hours**
- Part 4 (Electron Builder): **2-3 hours**
- Part 5 (GitHub Actions): **1-2 hours**
- Part 6 (Capability System): **4-6 hours**
- Part 7 (Final Polish): **1-2 hours**

**Total:** 10-16 hours remaining for full distribution-ready release.

---

**Status:** Orchestration complete. Ready to begin build system when you resume.
