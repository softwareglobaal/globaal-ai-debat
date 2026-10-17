#!/usr/bin/env bash
# Eén keer per dag starten in Terminal > New Terminal van Antigravity.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ ! "${ANTIGRAVITY_LS_ADDRESS:-}" =~ [^[:space:]] ]] ||
   [[ ! "${ANTIGRAVITY_CSRF_TOKEN:-}" =~ [^[:space:]] ]]; then
  echo "Antigravity-toegang ontbreekt; start in de Terminal van Antigravity: Terminal > New Terminal" >&2
  exit 2
fi
if [[ ! -x "$REPO/.venv/bin/python" ]]; then
  echo "Python-omgeving ontbreekt: $REPO/.venv/bin/python" >&2
  exit 2
fi
exec "$REPO/.venv/bin/python" "$REPO/brug.py" luister "$@"
