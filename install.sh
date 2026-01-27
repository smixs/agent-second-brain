#!/bin/bash
# Agent Second Brain — One-command installer
# Works on Mac and Windows WSL
# https://github.com/smixs/agent-second-brain

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Config
REPO_URL="https://github.com/smixs/agent-second-brain.git"
INSTALL_DIR="$HOME/agent-second-brain"

#######################################
# Print colored message
#######################################
info() { echo -e "${BLUE}ℹ${NC} $1"; }
success() { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
error() { echo -e "${RED}✗${NC} $1"; exit 1; }

#######################################
# Detect OS
#######################################
detect_os() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        OS="mac"
        info "Detected: macOS"
    elif grep -q Microsoft /proc/version 2>/dev/null; then
        OS="wsl"
        info "Detected: Windows WSL"
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        OS="linux"
        info "Detected: Linux"
    else
        error "Unsupported OS. This script works on Mac and Windows WSL only."
    fi
}

#######################################
# Check if command exists
#######################################
has_command() {
    command -v "$1" &> /dev/null
}

#######################################
# Install Homebrew (Mac only)
#######################################
install_homebrew() {
    if [[ "$OS" != "mac" ]]; then return; fi

    if has_command brew; then
        success "Homebrew already installed"
    else
        info "Installing Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

        # Add to PATH for current session
        if [[ -f /opt/homebrew/bin/brew ]]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
        elif [[ -f /usr/local/bin/brew ]]; then
            eval "$(/usr/local/bin/brew shellenv)"
        fi

        success "Homebrew installed"
    fi
}

#######################################
# Install dependencies
#######################################
install_dependencies() {
    info "Installing dependencies..."

    if [[ "$OS" == "mac" ]]; then
        # Node.js
        if ! has_command node; then
            info "Installing Node.js..."
            brew install node
        fi
        success "Node.js $(node --version)"

        # Python 3.12
        if ! has_command python3.12; then
            info "Installing Python 3.12..."
            brew install python@3.12
        fi
        success "Python $(python3.12 --version)"

        # Git
        if ! has_command git; then
            info "Installing Git..."
            brew install git
        fi
        success "Git $(git --version | head -1)"

    elif [[ "$OS" == "wsl" ]] || [[ "$OS" == "linux" ]]; then
        info "Updating apt packages..."
        sudo apt update && sudo apt upgrade -y

        # Node.js 20
        if ! has_command node; then
            info "Installing Node.js..."
            curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
            sudo apt install -y nodejs
        fi
        success "Node.js $(node --version)"

        # Python 3.12
        if ! has_command python3.12; then
            info "Installing Python 3.12..."
            sudo apt install -y software-properties-common
            sudo add-apt-repository -y ppa:deadsnakes/ppa
            sudo apt update
            sudo apt install -y python3.12 python3.12-venv python3.12-dev
        fi
        success "Python $(python3.12 --version)"

        # Git
        if ! has_command git; then
            info "Installing Git..."
            sudo apt install -y git curl wget
        fi
        success "Git $(git --version | head -1)"
    fi
}

#######################################
# Install uv (Python package manager)
#######################################
install_uv() {
    if has_command uv; then
        success "uv already installed: $(uv --version)"
    else
        info "Installing uv..."
        curl -LsSf https://astral.sh/uv/install.sh | sh

        # Add to PATH for current session
        export PATH="$HOME/.local/bin:$PATH"

        success "uv installed: $(uv --version)"
    fi
}

#######################################
# Install Claude Code CLI
#######################################
install_claude() {
    if has_command claude; then
        success "Claude Code already installed: $(claude --version)"
    else
        info "Installing Claude Code CLI..."
        npm install -g @anthropic-ai/claude-code
        success "Claude Code installed"
    fi
}

#######################################
# Clone repository
#######################################
clone_repo() {
    if [[ -d "$INSTALL_DIR" ]]; then
        warn "Directory $INSTALL_DIR already exists"
        read -p "Overwrite? (y/n): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -rf "$INSTALL_DIR"
        else
            error "Installation cancelled"
        fi
    fi

    info "Cloning repository..."
    git clone "$REPO_URL" "$INSTALL_DIR"
    success "Repository cloned to $INSTALL_DIR"
}

#######################################
# Prompt for token
#######################################
prompt_token() {
    local name="$1"
    local desc="$2"
    local url="$3"
    local var_name="$4"
    local optional="${5:-false}"

    echo
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}$name${NC}"
    echo "$desc"
    echo -e "Get it here: ${GREEN}$url${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    if [[ "$optional" == "true" ]]; then
        read -p "Enter token (or press Enter to skip): " token
    else
        while true; do
            read -p "Enter token: " token
            if [[ -n "$token" ]]; then
                break
            fi
            warn "This token is required"
        done
    fi

    eval "$var_name=\"$token\""
}

#######################################
# Collect tokens interactively
#######################################
collect_tokens() {
    echo
    echo -e "${GREEN}╔════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║           TOKEN CONFIGURATION                  ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════╝${NC}"
    echo
    echo "You'll need to provide 4 tokens. Instructions for each below."

    # Telegram Bot Token
    prompt_token \
        "1/4: Telegram Bot Token" \
        "Create a bot via @BotFather in Telegram:
1. Open Telegram and search for @BotFather
2. Send /newbot
3. Follow instructions to create your bot
4. Copy the token (looks like: 7123456789:AAHd...)" \
        "https://t.me/BotFather" \
        "TELEGRAM_BOT_TOKEN"

    # Telegram User ID
    prompt_token \
        "2/4: Your Telegram User ID" \
        "Get your ID via @userinfobot:
1. Search for @userinfobot in Telegram
2. Send any message
3. Copy your ID (just the number)" \
        "https://t.me/userinfobot" \
        "TELEGRAM_USER_ID"

    # Deepgram API Key
    prompt_token \
        "3/4: Deepgram API Key" \
        "For voice transcription (free \$200 credit):
1. Sign up at console.deepgram.com
2. Go to Settings → API Keys
3. Create new key and copy it" \
        "https://console.deepgram.com/" \
        "DEEPGRAM_API_KEY"

    # Todoist API Token (optional)
    prompt_token \
        "4/4: Todoist API Token (optional)" \
        "For task management:
1. Log in to todoist.com
2. Settings → Integrations → Developer
3. Copy the API token" \
        "https://todoist.com/app/settings/integrations/developer" \
        "TODOIST_API_KEY" \
        "true"
}

#######################################
# Create .env file
#######################################
create_env() {
    info "Creating .env file..."

    cat > "$INSTALL_DIR/.env" << EOF
# Telegram Bot Token (from @BotFather)
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN

# Deepgram API Key (from console.deepgram.com)
DEEPGRAM_API_KEY=$DEEPGRAM_API_KEY

# Todoist API Token (optional)
TODOIST_API_KEY=$TODOIST_API_KEY

# Path to vault (don't change)
VAULT_PATH=./vault

# Your Telegram ID (bot responds only to you)
ALLOWED_USER_IDS=[$TELEGRAM_USER_ID]
EOF

    success ".env file created"
}

#######################################
# Install Python dependencies
#######################################
install_python_deps() {
    info "Installing Python dependencies..."
    cd "$INSTALL_DIR"
    uv sync
    success "Python dependencies installed"
}

#######################################
# Install mcp-cli
#######################################
install_mcp_cli() {
    if has_command mcp-cli; then
        success "mcp-cli already installed"
    else
        info "Installing mcp-cli..."
        curl -fsSL https://raw.githubusercontent.com/philschmid/mcp-cli/main/install.sh | bash
        export PATH="$HOME/.local/bin:$PATH"
        success "mcp-cli installed"
    fi

    # Configure mcp-cli for Todoist if token provided
    if [[ -n "$TODOIST_API_KEY" ]]; then
        info "Configuring mcp-cli for Todoist..."
        mkdir -p ~/.config/mcp
        cat > ~/.config/mcp/mcp_servers.json << EOF
{
  "mcpServers": {
    "todoist": {
      "command": "npx",
      "args": ["-y", "@doist/todoist-ai"],
      "env": {
        "TODOIST_API_KEY": "$TODOIST_API_KEY"
      }
    }
  }
}
EOF
        success "mcp-cli configured"
    fi
}

#######################################
# Authenticate Claude
#######################################
auth_claude() {
    echo
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}Claude Authentication${NC}"
    echo "You need Claude Pro subscription (\$20/month) for this to work."
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo

    if claude auth status &>/dev/null; then
        success "Claude already authenticated"
    else
        info "Starting Claude authentication..."
        echo "A browser window will open. Log in with your Anthropic account."
        echo
        claude auth login
        success "Claude authenticated"
    fi
}

#######################################
# Setup autostart (optional)
#######################################
setup_autostart() {
    echo
    read -p "Configure autostart (bot runs when computer starts)? (y/n): " -n 1 -r
    echo

    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        info "Skipping autostart configuration"
        return
    fi

    if [[ "$OS" == "mac" ]]; then
        setup_launchd
    else
        setup_systemd
    fi
}

#######################################
# Setup launchd (Mac)
#######################################
setup_launchd() {
    info "Configuring launchd..."

    mkdir -p ~/Library/LaunchAgents

    cat > ~/Library/LaunchAgents/com.agent-second-brain.plist << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.agent-second-brain</string>
    <key>ProgramArguments</key>
    <array>
        <string>$HOME/.local/bin/uv</string>
        <string>run</string>
        <string>python</string>
        <string>-m</string>
        <string>d_brain</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$INSTALL_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$INSTALL_DIR/logs/bot.log</string>
    <key>StandardErrorPath</key>
    <string>$INSTALL_DIR/logs/bot-error.log</string>
</dict>
</plist>
EOF

    mkdir -p "$INSTALL_DIR/logs"
    launchctl load ~/Library/LaunchAgents/com.agent-second-brain.plist

    success "Autostart configured (launchd)"
    info "Bot will start automatically on login"
}

#######################################
# Setup systemd (Linux/WSL)
#######################################
setup_systemd() {
    info "Configuring systemd..."

    mkdir -p ~/.config/systemd/user

    cat > ~/.config/systemd/user/agent-second-brain.service << EOF
[Unit]
Description=Agent Second Brain Telegram Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=$HOME/.local/bin/uv run python -m d_brain
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF

    systemctl --user daemon-reload
    systemctl --user enable agent-second-brain
    systemctl --user start agent-second-brain

    success "Autostart configured (systemd)"
    info "Bot is running now and will start on boot"
}

#######################################
# Start bot manually
#######################################
start_bot() {
    echo
    echo -e "${GREEN}╔════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║           INSTALLATION COMPLETE!               ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════╝${NC}"
    echo

    if [[ "$OS" == "mac" ]] && [[ -f ~/Library/LaunchAgents/com.agent-second-brain.plist ]]; then
        echo "Bot is running in background."
        echo
        echo "Commands:"
        echo "  Stop:    launchctl unload ~/Library/LaunchAgents/com.agent-second-brain.plist"
        echo "  Start:   launchctl load ~/Library/LaunchAgents/com.agent-second-brain.plist"
        echo "  Logs:    tail -f $INSTALL_DIR/logs/bot.log"
    elif systemctl --user is-active --quiet agent-second-brain 2>/dev/null; then
        echo "Bot is running in background."
        echo
        echo "Commands:"
        echo "  Stop:    systemctl --user stop agent-second-brain"
        echo "  Start:   systemctl --user start agent-second-brain"
        echo "  Logs:    journalctl --user -u agent-second-brain -f"
    else
        echo "To start the bot manually:"
        echo
        echo -e "  ${GREEN}cd $INSTALL_DIR && uv run python -m d_brain${NC}"
        echo
        read -p "Start bot now? (y/n): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            cd "$INSTALL_DIR"
            info "Starting bot... (Ctrl+C to stop)"
            uv run python -m d_brain
        fi
    fi
}

#######################################
# Main
#######################################
main() {
    echo
    echo -e "${GREEN}╔════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║         AGENT SECOND BRAIN INSTALLER           ║${NC}"
    echo -e "${GREEN}║                                                 ║${NC}"
    echo -e "${GREEN}║   Voice-first AI assistant with memory         ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════╝${NC}"
    echo

    detect_os
    install_homebrew
    install_dependencies
    install_uv
    install_claude
    clone_repo
    collect_tokens
    create_env
    install_python_deps
    install_mcp_cli
    auth_claude
    setup_autostart
    start_bot
}

main "$@"
