#!/bin/bash
echo "Installing Sentinel Guardian security tools..."
sudo apt-get update -y
sudo apt-get install -y \
    nmap \
    tshark \
    sqlmap \
    gobuster \
    nikto \
    netcat-openbsd \
    masscan \
    dnsutils \
    whois \
    curl \
    wget \
    git

pip3 install --break-system-packages theHarvester 2>/dev/null || pip3 install theHarvester

echo ""
echo "Guardian tools installed successfully."
echo ""
nmap --version | head -1
sqlmap --version 2>/dev/null | head -1 || echo "sqlmap installed"
echo "Done."
