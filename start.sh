#!/usr/bin/env bash
# Start de webinterface van ai-debat (macOS en Linux) en open de browser.
cd "$(dirname "$0")"
if [ -x .venv/bin/python ]; then
  exec .venv/bin/python web.py
fi
exec python3 web.py
