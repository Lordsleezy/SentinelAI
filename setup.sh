#!/usr/bin/env bash
# Sentinel Earn — Linux/Mac Setup Script
# Run with: bash setup.sh

set -e  # Exit on error

echo ""
echo "========================================"
echo "  Sentinel Earn — Linux/Mac Setup"
echo "========================================"
echo ""

# Check Python version
echo "[1/8] Checking Python version..."
if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3 not found. Install Python 3.11+ from https://python.org"
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "  Found: Python $PYTHON_VERSION"

MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [ "$MAJOR" -lt 3 ] || { [ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 11 ]; }; then
    echo "ERROR: Python 3.11+ required (found $MAJOR.$MINOR)"
    exit 1
fi

# Check if venv exists
echo ""
echo "[2/8] Setting up virtual environment..."
if [ -d "venv" ]; then
    echo "  Virtual environment already exists (venv/)"
else
    echo "  Creating virtual environment..."
    python3 -m venv venv
    echo "  Created venv/"
fi

# Activate venv
echo ""
echo "[3/8] Activating virtual environment..."
source venv/bin/activate
echo "  Activated venv"

# Upgrade pip
echo ""
echo "[4/8] Upgrading pip..."
python -m pip install --upgrade pip --quiet
echo "  pip upgraded"

# Install dependencies
echo ""
echo "[5/8] Installing Python dependencies..."
pip install -r requirements.txt --quiet
echo "  Installed all dependencies from requirements.txt"

# Install Playwright browsers
echo ""
echo "[6/8] Installing Playwright Chromium..."
python -m playwright install chromium
echo "  Playwright Chromium installed"

# Check Ollama
echo ""
echo "[7/8] Checking Ollama connectivity..."
if curl -s --max-time 3 http://127.0.0.1:11434 > /dev/null 2>&1; then
    echo "  Ollama is running"
    
    # Check if model exists
    echo "  Checking for qwen2.5-coder:14b model..."
    if ollama list 2>/dev/null | grep -q "qwen2.5-coder:14b"; then
        echo "  Model qwen2.5-coder:14b found"
    else
        echo "  WARNING: Model qwen2.5-coder:14b not found"
        echo "  Run: ollama pull qwen2.5-coder:14b"
    fi
else
    echo "  WARNING: Ollama not reachable at http://127.0.0.1:11434"
    echo "  Install Ollama from: https://ollama.com"
    echo "  Then run: ollama pull qwen2.5-coder:14b"
fi

# Create directories
echo ""
echo "[8/8] Creating required directories..."
if [ ! -d "data" ]; then
    mkdir -p data
    echo "  Created data/"
else
    echo "  data/ already exists"
fi

if [ ! -d "workspace" ]; then
    mkdir -p workspace
    echo "  Created workspace/"
else
    echo "  workspace/ already exists"
fi

# Initialize database
echo ""
echo "  Initializing database..."
python -c "import db; db.init_db(); print('Database initialized')"
echo "  Database ready at data/sentinel_earn.db"

# Check .env
echo ""
echo "========================================"
echo "  Setup Complete!"
echo "========================================"
echo ""

if [ ! -f ".env" ]; then
    echo "NEXT STEPS:"
    echo "  1. Copy .env.example to .env:"
    echo "     cp .env.example .env"
    echo ""
    echo "  2. Edit .env and add your GitHub credentials:"
    echo "     GITHUB_TOKEN=ghp_your_token_here"
    echo "     GITHUB_USERNAME=your_username"
    echo ""
    echo "  3. Pull the Ollama model (if not done):"
    echo "     ollama pull qwen2.5-coder:14b"
    echo ""
    echo "  4. Test in dry-run mode:"
    echo "     python main.py --dry-run --scan-now"
    echo ""
    echo "  5. Start the full agent:"
    echo "     python main.py"
    echo "     Dashboard: http://localhost:8765"
else
    echo ".env file found - you're ready to go!"
    echo ""
    echo "RUN THE AGENT:"
    echo "  Dry-run test:  python main.py --dry-run --scan-now"
    echo "  Full agent:    python main.py"
    echo "  Dashboard:     http://localhost:8765"
fi

echo ""
