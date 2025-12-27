#!/bin/bash

# =============================================================================
# Agent Second Brain - VPS Setup Script
# =============================================================================
# One-command setup for your personal AI assistant
# Usage: curl -fsSL https://raw.githubusercontent.com/YOUR_USER/agent-second-brain/main/setup.sh | bash
# Or: bash setup.sh
# =============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Emojis (safe for most terminals)
CHECK="[OK]"
CROSS="[X]"
WARN="[!]"
ARROW="-->"
GEAR="[*]"

# =============================================================================
# Helper functions
# =============================================================================

print_banner() {
    echo ""
    echo -e "${PURPLE}${BOLD}"
    echo "  ╔═══════════════════════════════════════════════════════════╗"
    echo "  ║                                                           ║"
    echo "  ║          AGENT SECOND BRAIN - VPS SETUP                   ║"
    echo "  ║                                                           ║"
    echo "  ║   Personal AI Assistant with Long-term Memory             ║"
    echo "  ║                                                           ║"
    echo "  ╚═══════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
    echo ""
}

info() {
    echo -e "${BLUE}${GEAR}${NC} $1"
}

success() {
    echo -e "${GREEN}${CHECK}${NC} $1"
}

warn() {
    echo -e "${YELLOW}${WARN}${NC} $1"
}

error() {
    echo -e "${RED}${CROSS}${NC} $1"
}

step() {
    echo ""
    echo -e "${CYAN}${BOLD}${ARROW} $1${NC}"
    echo -e "${CYAN}$(printf '%.0s─' {1..60})${NC}"
}

ask() {
    echo -e "${YELLOW}?${NC} $1"
}

# =============================================================================
# Validation functions
# =============================================================================

validate_telegram_token() {
    local token="$1"
    # Telegram bot token format: 123456789:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
    if [[ $token =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]]; then
        return 0
    fi
    return 1
}

validate_telegram_id() {
    local id="$1"
    # Telegram ID is a positive integer
    if [[ $id =~ ^[0-9]+$ ]] && [ "$id" -gt 0 ]; then
        return 0
    fi
    return 1
}

validate_deepgram_key() {
    local key="$1"
    # Deepgram key is alphanumeric, typically 40+ chars
    if [[ $key =~ ^[A-Za-z0-9]+$ ]] && [ ${#key} -ge 20 ]; then
        return 0
    fi
    return 1
}

validate_todoist_key() {
    local key="$1"
    # Todoist API token is alphanumeric, 40 chars
    if [[ $key =~ ^[A-Za-z0-9]+$ ]] && [ ${#key} -ge 30 ]; then
        return 0
    fi
    return 1
}

# =============================================================================
# Check functions
# =============================================================================

check_root() {
    if [ "$EUID" -eq 0 ]; then
        error "Do not run this script as root!"
        echo "  Create a regular user first: adduser myuser && usermod -aG sudo myuser"
        echo "  Then run: su - myuser && bash setup.sh"
        exit 1
    fi
}

check_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        if [[ "$ID" != "ubuntu" && "$ID" != "debian" ]]; then
            warn "This script is tested on Ubuntu/Debian. You're running: $ID"
            read -p "Continue anyway? (y/N): " -r REPLY < /dev/tty
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 1
            fi
        fi
    fi
}

check_command() {
    command -v "$1" &> /dev/null
}

# =============================================================================
# Installation functions
# =============================================================================

install_system_deps() {
    step "Installing system dependencies"

    info "Updating package list..."
    sudo apt-get update -qq

    info "Installing git, curl, wget, build-essential..."
    sudo apt-get install -y -qq git curl wget build-essential software-properties-common

    success "System dependencies installed"
}

install_python() {
    step "Installing Python 3.12"

    if check_command python3.12; then
        success "Python 3.12 already installed"
        return
    fi

    info "Adding deadsnakes PPA..."
    sudo add-apt-repository -y ppa:deadsnakes/ppa
    sudo apt-get update -qq

    info "Installing Python 3.12..."
    sudo apt-get install -y -qq python3.12 python3.12-venv python3.12-dev

    success "Python 3.12 installed"
}

install_uv() {
    step "Installing uv (Python package manager)"

    if check_command uv; then
        success "uv already installed"
        return
    fi

    info "Downloading and installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh

    # Add to current session
    export PATH="$HOME/.local/bin:$PATH"

    # Add to .bashrc if not already there
    if ! grep -q 'export PATH="$HOME/.local/bin:$PATH"' ~/.bashrc 2>/dev/null; then
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
    fi

    success "uv installed"
}

install_nodejs() {
    step "Installing Node.js 20"

    if check_command node; then
        NODE_VERSION=$(node --version | cut -d'v' -f2 | cut -d'.' -f1)
        if [ "$NODE_VERSION" -ge 18 ]; then
            success "Node.js $(node --version) already installed"
            return
        fi
    fi

    info "Adding NodeSource repository..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -

    info "Installing Node.js..."
    sudo apt-get install -y -qq nodejs

    success "Node.js $(node --version) installed"
}

install_claude_cli() {
    step "Installing Claude CLI"

    if check_command claude; then
        success "Claude CLI already installed: $(claude --version 2>/dev/null || echo 'version unknown')"
        return
    fi

    info "Installing @anthropic-ai/claude-code globally..."
    sudo npm install -g @anthropic-ai/claude-code

    success "Claude CLI installed"
}

# =============================================================================
# Configuration functions
# =============================================================================

clone_repository() {
    step "Setting up project"

    PROJECTS_DIR="$HOME/projects"
    PROJECT_DIR="$PROJECTS_DIR/agent-second-brain"

    mkdir -p "$PROJECTS_DIR"

    if [ -d "$PROJECT_DIR" ]; then
        warn "Project directory already exists: $PROJECT_DIR"
        read -p "Remove and re-clone? (y/N): " -r REPLY < /dev/tty
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -rf "$PROJECT_DIR"
        else
            cd "$PROJECT_DIR"
            success "Using existing directory"
            return
        fi
    fi

    ask "Enter your GitHub username (the one where you forked the repo):"
    read -r GITHUB_USER < /dev/tty

    if [ -z "$GITHUB_USER" ]; then
        error "GitHub username cannot be empty"
        exit 1
    fi

    REPO_URL="https://github.com/$GITHUB_USER/agent-second-brain.git"

    info "Cloning from $REPO_URL..."

    if ! git clone "$REPO_URL" "$PROJECT_DIR" 2>/dev/null; then
        error "Failed to clone repository!"
        echo "  Make sure you've forked the repo and the username is correct"
        exit 1
    fi

    cd "$PROJECT_DIR"
    success "Repository cloned to $PROJECT_DIR"

    # Save GitHub user for later
    echo "$GITHUB_USER" > .github_user
}

collect_tokens() {
    step "Collecting API tokens"
    echo ""
    echo "You'll need these tokens (get them from the services):"
    echo "  - Telegram Bot Token (from @BotFather)"
    echo "  - Your Telegram ID (from @userinfobot)"
    echo "  - Deepgram API Key (from console.deepgram.com)"
    echo "  - Todoist API Token (from Todoist Settings > Integrations > Developer)"
    echo ""

    # Telegram Bot Token
    while true; do
        ask "Telegram Bot Token (from @BotFather):"
        read -r TELEGRAM_BOT_TOKEN < /dev/tty
        if validate_telegram_token "$TELEGRAM_BOT_TOKEN"; then
            success "Token format valid"
            break
        else
            error "Invalid token format. Should be like: 123456789:ABC-DEF1234ghIkl-zyx57W2v"
        fi
    done

    # Telegram User ID
    while true; do
        ask "Your Telegram User ID (from @userinfobot):"
        read -r TELEGRAM_USER_ID < /dev/tty
        if validate_telegram_id "$TELEGRAM_USER_ID"; then
            success "User ID valid"
            break
        else
            error "Invalid User ID. Should be a number like: 123456789"
        fi
    done

    # Deepgram API Key
    while true; do
        ask "Deepgram API Key (from console.deepgram.com):"
        read -r DEEPGRAM_API_KEY < /dev/tty
        if validate_deepgram_key "$DEEPGRAM_API_KEY"; then
            success "API Key format valid"
            break
        else
            error "Invalid API key format. Should be alphanumeric, 20+ characters"
        fi
    done

    # Todoist API Token
    while true; do
        ask "Todoist API Token (from Settings > Integrations > Developer):"
        read -r TODOIST_API_KEY < /dev/tty
        if validate_todoist_key "$TODOIST_API_KEY"; then
            success "API Token format valid"
            break
        else
            error "Invalid API token format. Should be alphanumeric, 30+ characters"
        fi
    done
}

create_env_file() {
    step "Creating .env file"

    ENV_FILE="$PROJECT_DIR/.env"

    if [ -f "$ENV_FILE" ]; then
        warn ".env file already exists"
        read -p "Overwrite? (y/N): " -r REPLY < /dev/tty
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            success "Keeping existing .env"
            return
        fi
    fi

    cat > "$ENV_FILE" << EOF
# Telegram Bot API token from @BotFather
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN

# Deepgram API key for voice transcription
DEEPGRAM_API_KEY=$DEEPGRAM_API_KEY

# Todoist API key for task management
TODOIST_API_KEY=$TODOIST_API_KEY

# Path to Obsidian vault directory
VAULT_PATH=./vault

# JSON array of Telegram user IDs allowed to use the bot
ALLOWED_USER_IDS=[$TELEGRAM_USER_ID]
EOF

    chmod 600 "$ENV_FILE"
    success ".env file created (permissions: 600)"
}

install_dependencies() {
    step "Installing Python dependencies"

    cd "$PROJECT_DIR"

    info "Running uv sync..."
    "$HOME/.local/bin/uv" sync

    success "Dependencies installed"
}

configure_systemd() {
    step "Configuring systemd service"

    SERVICE_FILE="/etc/systemd/system/d-brain-bot.service"
    SERVICE_NAME="d-brain-bot"

    # Generate service file content
    SERVICE_CONTENT="[Unit]
Description=d-brain Telegram Bot
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$HOME/.local/bin/uv run python -m d_brain
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target"

    info "Creating systemd service..."
    echo "$SERVICE_CONTENT" | sudo tee "$SERVICE_FILE" > /dev/null

    info "Reloading systemd daemon..."
    sudo systemctl daemon-reload

    info "Enabling service to start on boot..."
    sudo systemctl enable "$SERVICE_NAME"

    info "Starting service..."
    sudo systemctl start "$SERVICE_NAME"

    # Wait a moment for service to start
    sleep 2

    success "Systemd service configured"
}

configure_git_remote() {
    step "Configuring Git for push access"

    cd "$PROJECT_DIR"

    # Set git config
    git config user.name "Agent Second Brain Bot"
    git config user.email "bot@localhost"

    ask "Do you want to configure GitHub push access? (for auto-sync)"
    read -p "(y/N): " -r REPLY < /dev/tty

    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        warn "Skipping GitHub push configuration"
        return
    fi

    echo ""
    echo "Create a Personal Access Token on GitHub:"
    echo "  1. Go to: github.com > Settings > Developer settings > Personal access tokens > Tokens (classic)"
    echo "  2. Generate new token with 'repo' scope"
    echo "  3. Copy the token"
    echo ""

    ask "Enter your GitHub Personal Access Token:"
    read -rs GITHUB_TOKEN < /dev/tty
    echo ""

    if [ -z "$GITHUB_TOKEN" ]; then
        warn "No token provided, skipping"
        return
    fi

    GITHUB_USER=$(cat .github_user 2>/dev/null || echo "")

    if [ -z "$GITHUB_USER" ]; then
        ask "Enter your GitHub username:"
        read -r GITHUB_USER < /dev/tty
    fi

    git remote set-url origin "https://$GITHUB_TOKEN@github.com/$GITHUB_USER/agent-second-brain.git"

    success "Git remote configured for push"
}

# =============================================================================
# Status and verification
# =============================================================================

check_status() {
    step "Final status check"

    ERRORS=()
    WARNINGS=()

    echo ""

    # Check Python
    if check_command python3.12; then
        success "Python 3.12: $(python3.12 --version)"
    else
        ERRORS+=("Python 3.12 not found")
    fi

    # Check uv
    if check_command uv || [ -f "$HOME/.local/bin/uv" ]; then
        success "uv: $($HOME/.local/bin/uv --version 2>/dev/null || uv --version)"
    else
        ERRORS+=("uv not found")
    fi

    # Check Node.js
    if check_command node; then
        success "Node.js: $(node --version)"
    else
        ERRORS+=("Node.js not found")
    fi

    # Check Claude CLI
    if check_command claude; then
        success "Claude CLI: installed"
    else
        WARNINGS+=("Claude CLI not found (needed for AI processing)")
    fi

    # Check .env
    if [ -f "$PROJECT_DIR/.env" ]; then
        success ".env file: exists"
    else
        ERRORS+=(".env file not found")
    fi

    # Check systemd service
    if systemctl is-active --quiet d-brain-bot; then
        success "Bot service: running"
    else
        STATUS=$(systemctl is-active d-brain-bot 2>/dev/null || echo "unknown")
        ERRORS+=("Bot service not running (status: $STATUS)")
    fi

    echo ""

    # Summary
    if [ ${#ERRORS[@]} -eq 0 ] && [ ${#WARNINGS[@]} -eq 0 ]; then
        echo -e "${GREEN}${BOLD}"
        echo "  ╔═══════════════════════════════════════════════════════════╗"
        echo "  ║                                                           ║"
        echo "  ║                    SETUP COMPLETE!                        ║"
        echo "  ║                                                           ║"
        echo "  ╚═══════════════════════════════════════════════════════════╝"
        echo -e "${NC}"
        echo ""
        echo "  Next steps:"
        echo "    1. Open Telegram and find your bot"
        echo "    2. Send /start to test"
        echo "    3. Send a voice message!"
        echo ""
        echo "  Useful commands:"
        echo "    - View logs:    sudo journalctl -u d-brain-bot -f"
        echo "    - Restart bot:  sudo systemctl restart d-brain-bot"
        echo "    - Stop bot:     sudo systemctl stop d-brain-bot"
        echo ""
    else
        if [ ${#ERRORS[@]} -gt 0 ]; then
            echo -e "${RED}${BOLD}ERRORS:${NC}"
            for err in "${ERRORS[@]}"; do
                error "$err"
            done
            echo ""
        fi

        if [ ${#WARNINGS[@]} -gt 0 ]; then
            echo -e "${YELLOW}${BOLD}WARNINGS:${NC}"
            for wrn in "${WARNINGS[@]}"; do
                warn "$wrn"
            done
            echo ""
        fi

        echo "Troubleshooting:"
        echo "  - Check logs: sudo journalctl -u d-brain-bot -n 50"
        echo "  - Check .env: cat $PROJECT_DIR/.env"
        echo "  - Manual start: cd $PROJECT_DIR && uv run python -m d_brain"
        echo ""
    fi
}

authorize_claude() {
    step "Claude CLI Authorization"

    if claude auth status 2>/dev/null | grep -q "Logged in"; then
        success "Claude CLI already authorized"
        return
    fi

    warn "Claude CLI needs authorization"
    echo ""
    echo "Run this command manually:"
    echo -e "  ${CYAN}claude auth login${NC}"
    echo ""
    echo "This will open a browser for authentication."
    echo "After authorizing, the bot will be able to use Claude for AI processing."
    echo ""
}

# =============================================================================
# Main script
# =============================================================================

main() {
    print_banner

    check_root
    check_os

    echo "This script will:"
    echo "  1. Install required software (Python, Node.js, uv, Claude CLI)"
    echo "  2. Clone your fork of the repository"
    echo "  3. Ask for your API tokens"
    echo "  4. Create configuration files"
    echo "  5. Set up auto-start service"
    echo ""

    read -p "Ready to start? (Y/n): " -r REPLY < /dev/tty
    if [[ $REPLY =~ ^[Nn]$ ]]; then
        echo "Setup cancelled."
        exit 0
    fi

    # Installation
    install_system_deps
    install_python
    install_uv
    install_nodejs
    install_claude_cli

    # Configuration
    clone_repository
    collect_tokens
    create_env_file
    install_dependencies
    configure_systemd
    configure_git_remote
    authorize_claude

    # Final check
    check_status
}

# Run main if script is executed (not sourced)
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
