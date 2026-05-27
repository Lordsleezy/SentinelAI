# Sentinel Earn — Makefile
# Requires GNU Make. Windows users: https://gnuwin32.sourceforge.net/packages/make.htm
# Alternative: run the python commands directly (see README)

.PHONY: install run dry-run dashboard scan execute clean help

help:
	@echo ""
	@echo "  Sentinel Earn — Makefile targets"
	@echo ""
	@echo "  make install      Install Python deps + Playwright browser"
	@echo "  make run          Start full agent (scanner + executor + dashboard)"
	@echo "  make dry-run      Safe dry-run mode (no GitHub calls)"
	@echo "  make dashboard    Dashboard only (http://localhost:8765)"
	@echo "  make scan         Run one scan immediately then exit"
	@echo "  make execute      Run executor once then exit"
	@echo "  make clean        Remove workspace/, __pycache__, *.pyc"
	@echo ""

install:
	pip install -r requirements.txt
	python -m playwright install chromium
	@echo ""
	@echo "  Next: copy .env.example to .env and add your GitHub credentials"
	@echo "  Then: ollama pull qwen2.5-coder:14b"
	@echo ""

run:
	python main.py

dry-run:
	python main.py --dry-run

dashboard:
	python main.py --dashboard-only

scan:
	python main.py --scan-now

execute:
	python main.py --execute-now

clean:
	python -c "import shutil, pathlib; [shutil.rmtree(p, ignore_errors=True) for p in ['workspace']]; [p.unlink() for p in pathlib.Path('.').rglob('*.pyc')]"
	@echo "Cleaned workspace/ and *.pyc files"
