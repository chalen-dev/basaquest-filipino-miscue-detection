#!/usr/bin/env bash
# Installs Claude Code inside a Colab VM terminal (Pro's built-in Terminal,
# a colab-xterm session, or an SSH session - anything with a real TTY).
# Not an official Anthropic/Google integration - Colab VMs are ephemeral, so
# this needs re-running once per fresh runtime. See training/README.md for
# the full walkthrough of why/how.
set -e

echo "== Trying the native Claude Code installer (no Node.js required) =="
if curl -fsSL https://claude.ai/install.sh | bash; then
    echo "Native install succeeded."
else
    echo "Native installer failed or unavailable - falling back to npm."
    echo "== Checking Node.js =="
    if ! command -v node >/dev/null 2>&1 || [ "$(node -v | sed 's/v//' | cut -d. -f1)" -lt 18 ]; then
        echo "Installing Node.js 20 via nvm..."
        curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
        export NVM_DIR="$HOME/.nvm"
        # shellcheck disable=SC1091
        [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
        nvm install 20
        nvm use 20
    fi
    node --version
    echo "== Installing Claude Code via npm =="
    npm install -g @anthropic-ai/claude-code
fi

echo
echo "== Done =="
echo "Run: claude"
echo "First time in this VM, it'll prompt you to log in (opens a URL you paste"
echo "into any browser - not necessarily one on this machine) or you can set"
echo "ANTHROPIC_API_KEY instead (billed separately per-token, from console.anthropic.com)."
