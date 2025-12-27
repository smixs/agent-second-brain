#!/bin/bash

# =============================================================================
# Agent Second Brain - Bootstrap Script
# =============================================================================
# Downloads and runs the full setup script
#
# Usage (after forking the repo):
#   curl -fsSL https://raw.githubusercontent.com/YOUR_USER/agent-second-brain/main/bootstrap.sh | bash
#
# Or with your username:
#   curl -fsSL https://raw.githubusercontent.com/YOUR_USER/agent-second-brain/main/bootstrap.sh | bash -s YOUR_USER
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

echo ""
echo -e "${CYAN}Agent Second Brain - Bootstrap${NC}"
echo ""

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo -e "${RED}[X] Do not run as root!${NC}"
    echo "    Create a user first: adduser myuser && usermod -aG sudo myuser"
    echo "    Then: su - myuser"
    exit 1
fi

# Get GitHub username
GITHUB_USER="${1:-}"

if [ -z "$GITHUB_USER" ]; then
    echo -e "${CYAN}Enter your GitHub username (where you forked the repo):${NC}"
    # Read from /dev/tty to handle curl | bash case
    read -r GITHUB_USER < /dev/tty
fi

if [ -z "$GITHUB_USER" ]; then
    echo -e "${RED}[X] GitHub username is required${NC}"
    echo ""
    echo "Usage:"
    echo "  curl -fsSL URL | bash -s YOUR_GITHUB_USER"
    echo "  Example: curl -fsSL URL | bash -s smixs"
    exit 1
fi

SETUP_URL="https://raw.githubusercontent.com/$GITHUB_USER/agent-second-brain/main/setup.sh"

echo ""
echo "Downloading setup script from:"
echo "  $SETUP_URL"
echo ""

# Check if curl or wget available
if command -v curl &> /dev/null; then
    SETUP_SCRIPT=$(curl -fsSL "$SETUP_URL")
elif command -v wget &> /dev/null; then
    SETUP_SCRIPT=$(wget -qO- "$SETUP_URL")
else
    echo -e "${RED}[X] Neither curl nor wget found. Install one first:${NC}"
    echo "    sudo apt install curl"
    exit 1
fi

if [ -z "$SETUP_SCRIPT" ]; then
    echo -e "${RED}[X] Failed to download setup script${NC}"
    echo "    Make sure you've forked the repo and the username is correct"
    exit 1
fi

echo -e "${GREEN}[OK] Setup script downloaded${NC}"
echo ""

# Run the setup script
echo "Starting setup..."
echo ""

# Create temp file and run
TEMP_SCRIPT=$(mktemp)
echo "$SETUP_SCRIPT" > "$TEMP_SCRIPT"
chmod +x "$TEMP_SCRIPT"
bash "$TEMP_SCRIPT"
rm -f "$TEMP_SCRIPT"
