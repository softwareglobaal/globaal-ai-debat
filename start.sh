#!/usr/bin/env bash
# Start de webinterface van ai-debat (macOS en Linux) en open de browser.
cd "$(dirname "$0")"
# claude staat meestal in ~/.local/bin en codex via Homebrew in /opt/homebrew/bin. Vanuit
# Finder of een kale shell staan die niet op PATH, en dan vindt debat.vind() ze niet.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
if [ -x .venv/bin/python ]; then
  exec .venv/bin/python web.py
fi
exec python3 web.py
