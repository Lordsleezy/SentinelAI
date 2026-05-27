# Sentinel Earn — Windows Setup Script (PowerShell)
# Run with: powershell -ExecutionPolicy Bypass -File setup.ps1

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Sentinel Earn — Windows Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check Python version
Write-Host "[1/8] Checking Python version..." -ForegroundColor Yellow
$pythonVersion = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Python not found. Install Python 3.11+ from https://python.org" -ForegroundColor Red
    exit 1
}
Write-Host "  Found: $pythonVersion" -ForegroundColor Green

$versionMatch = $pythonVersion -match "Python (\d+)\.(\d+)"
if ($versionMatch) {
    $major = [int]$Matches[1]
    $minor = [int]$Matches[2]
    if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) {
        Write-Host "ERROR: Python 3.11+ required (found $major.$minor)" -ForegroundColor Red
        exit 1
    }
}

# Check if venv exists
Write-Host ""
Write-Host "[2/8] Setting up virtual environment..." -ForegroundColor Yellow
if (Test-Path "venv") {
    Write-Host "  Virtual environment already exists (venv/)" -ForegroundColor Green
} else {
    Write-Host "  Creating virtual environment..."
    python -m venv venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Failed to create virtual environment" -ForegroundColor Red
        exit 1
    }
    Write-Host "  Created venv/" -ForegroundColor Green
}

# Activate venv
Write-Host ""
Write-Host "[3/8] Activating virtual environment..." -ForegroundColor Yellow
& "venv\Scripts\Activate.ps1"
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to activate venv. Try running:" -ForegroundColor Red
    Write-Host "  Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser" -ForegroundColor Yellow
    exit 1
}
Write-Host "  Activated venv" -ForegroundColor Green

# Upgrade pip
Write-Host ""
Write-Host "[4/8] Upgrading pip..." -ForegroundColor Yellow
python -m pip install --upgrade pip --quiet
Write-Host "  pip upgraded" -ForegroundColor Green

# Install dependencies
Write-Host ""
Write-Host "[5/8] Installing Python dependencies..." -ForegroundColor Yellow
pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to install dependencies" -ForegroundColor Red
    exit 1
}
Write-Host "  Installed all dependencies from requirements.txt" -ForegroundColor Green

# Install Playwright browsers
Write-Host ""
Write-Host "[6/8] Installing Playwright Chromium..." -ForegroundColor Yellow
python -m playwright install chromium
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to install Playwright browser" -ForegroundColor Red
    exit 1
}
Write-Host "  Playwright Chromium installed" -ForegroundColor Green

# Check Ollama
Write-Host ""
Write-Host "[7/8] Checking Ollama connectivity..." -ForegroundColor Yellow
try {
    $ollamaResponse = Invoke-WebRequest -Uri "http://127.0.0.1:11434" -Method GET -TimeoutSec 3 -ErrorAction Stop
    Write-Host "  Ollama is running" -ForegroundColor Green
    
    # Check if model exists
    Write-Host "  Checking for qwen2.5-coder:14b model..."
    $modelCheck = ollama list 2>&1 | Select-String "qwen2.5-coder:14b"
    if ($modelCheck) {
        Write-Host "  Model qwen2.5-coder:14b found" -ForegroundColor Green
    } else {
        Write-Host "  WARNING: Model qwen2.5-coder:14b not found" -ForegroundColor Yellow
        Write-Host "  Run: ollama pull qwen2.5-coder:14b" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  WARNING: Ollama not reachable at http://127.0.0.1:11434" -ForegroundColor Yellow
    Write-Host "  Install Ollama from: https://ollama.com" -ForegroundColor Yellow
    Write-Host "  Then run: ollama pull qwen2.5-coder:14b" -ForegroundColor Yellow
}

# Create directories
Write-Host ""
Write-Host "[8/8] Creating required directories..." -ForegroundColor Yellow
if (-not (Test-Path "data")) {
    New-Item -ItemType Directory -Path "data" | Out-Null
    Write-Host "  Created data/" -ForegroundColor Green
} else {
    Write-Host "  data/ already exists" -ForegroundColor Green
}

if (-not (Test-Path "workspace")) {
    New-Item -ItemType Directory -Path "workspace" | Out-Null
    Write-Host "  Created workspace/" -ForegroundColor Green
} else {
    Write-Host "  workspace/ already exists" -ForegroundColor Green
}

# Initialize database
Write-Host ""
Write-Host "  Initializing database..."
python -c "import db; db.init_db(); print('Database initialized')"
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to initialize database" -ForegroundColor Red
    exit 1
}
Write-Host "  Database ready at data/sentinel_earn.db" -ForegroundColor Green

# Check .env
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Setup Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path ".env")) {
    Write-Host "NEXT STEPS:" -ForegroundColor Yellow
    Write-Host "  1. Copy .env.example to .env:" -ForegroundColor White
    Write-Host "     copy .env.example .env" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  2. Edit .env and add your GitHub credentials:" -ForegroundColor White
    Write-Host "     GITHUB_TOKEN=ghp_your_token_here" -ForegroundColor Cyan
    Write-Host "     GITHUB_USERNAME=your_username" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  3. Pull the Ollama model (if not done):" -ForegroundColor White
    Write-Host "     ollama pull qwen2.5-coder:14b" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  4. Test in dry-run mode:" -ForegroundColor White
    Write-Host "     python main.py --dry-run --scan-now" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  5. Start the full agent:" -ForegroundColor White
    Write-Host "     python main.py" -ForegroundColor Cyan
    Write-Host "     Dashboard: http://localhost:8765" -ForegroundColor Cyan
} else {
    Write-Host ".env file found - you're ready to go!" -ForegroundColor Green
    Write-Host ""
    Write-Host "RUN THE AGENT:" -ForegroundColor Yellow
    Write-Host "  Dry-run test:  python main.py --dry-run --scan-now" -ForegroundColor Cyan
    Write-Host "  Full agent:    python main.py" -ForegroundColor Cyan
    Write-Host "  Dashboard:     http://localhost:8765" -ForegroundColor Cyan
}

Write-Host ""
