#!/bin/bash
# Installeer de overleg-brug als door Antigravity bewaakte sidecar.
set -euo pipefail
umask 077

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
CONFIG="${ANTIGRAVITY_CONFIG_DIR:-$HOME/.gemini/config}"
SIDECAR="$CONFIG/sidecars/overleg-brug"
PY="$REPO/.venv/bin/python"
ACTIE="installeer"
WACHT=1
LAAT_STAAN=0

fout() { echo "installeer_sidecar.sh: $*" >&2; exit 2; }

gebruik() {
  cat <<'EOF'
Gebruik: installeer_sidecar.sh [--toon | --verwijder | --niet-wachten | --laat-staan | --help]
  --toon          toon de sidecar.json zonder iets te wijzigen
  --verwijder      verwijder alleen de sidecar overleg-brug
  --niet-wachten   installeer en toon direct de huidige status
  --laat-staan     laat een bestaande terminal-luisteraar draaien
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --toon) ACTIE="toon" ;;
    --verwijder) ACTIE="verwijder" ;;
    --niet-wachten) WACHT=0 ;;
    --laat-staan) LAAT_STAAN=1 ;;
    --help|-h) gebruik; exit 0 ;;
    *) fout "onbekende optie: $1 (zie --help)" ;;
  esac
  shift
done

if [ "$ACTIE" = "verwijder" ]; then
  rm -rf -- "$SIDECAR"
  echo "Sidecar overleg-brug verwijderd"
  exit 0
fi

if [ "$ACTIE" = "toon" ] && [ ! -x "$PY" ]; then
  PY="$(command -v python3 || true)"
fi
[ -x "$PY" ] || fout "Python-omgeving ontbreekt: $REPO/.venv/bin/python"

manifest() {
  "$PY" - "$REPO/brug.sh" <<'PYCODE'
import json
import sys

print(json.dumps({
    "command": "/bin/bash",
    "args": [sys.argv[1], "--ouder-bewaken", "--wacht-op-slot"],
    "restart_policy": "always",
    "description": "Start en bewaakt de brug voor driehoeksoverleg",
}, ensure_ascii=False, indent=2))
PYCODE
}

if [ "$ACTIE" = "toon" ]; then
  manifest
  exit 0
fi

[ -x "$REPO/.venv/bin/python" ] || fout "Python-omgeving ontbreekt: $REPO/.venv/bin/python"
[ -d "$CONFIG" ] || fout "Antigravity-configmap ontbreekt: $CONFIG (installeer Antigravity 2.x eerst)"
mkdir -p -- "$SIDECAR"
chmod 700 "$SIDECAR"
TIJDELIJK="$(mktemp "$SIDECAR/.sidecar.json.XXXXXX")"
trap 'rm -f -- "$TIJDELIJK"' EXIT
manifest > "$TIJDELIJK"
chmod 600 "$TIJDELIJK"
if [ -f "$SIDECAR/sidecar.json" ] && [ ! -L "$SIDECAR/sidecar.json" ] &&
   cmp -s "$TIJDELIJK" "$SIDECAR/sidecar.json"; then
  chmod 600 "$SIDECAR/sidecar.json"
  rm -f -- "$TIJDELIJK"
else
  mv -f -- "$TIJDELIJK" "$SIDECAR/sidecar.json"
fi
trap - EXIT

toestand() {
  "$PY" - "$REPO" <<'PYCODE'
import sys

sys.path.insert(0, sys.argv[1])
import brug

basis = brug.brugmap()
hartslag = brug.lees_hartslag(basis)
bron = ""
pid = 0
if brug._levend(hartslag):
    waarde = hartslag.get("bron", "terminal")
    if waarde in ("terminal", "sidecar"):
        bron = waarde
        pid = hartslag["pid"]
reserve = any(slag.get("bron") == "sidecar" for slag in brug.lees_reserves(basis))
try:
    bezig = not (basis / "bezig").is_dir() or any((basis / "bezig").iterdir())
    wachtrij = not (basis / "wachtrij").is_dir() or any(
        pad.is_file() and pad.name.endswith(".json") and
        brug.ID.fullmatch(pad.name[:-5])
        for pad in (basis / "wachtrij").iterdir())
except OSError:
    bezig = True
    wachtrij = True
print(f"{bron}|{pid}|{int(reserve)}|{int(bezig)}|{int(wachtrij)}")
PYCODE
}

is_luisteraar() {
  local pid="$1" opdracht
  [[ "$pid" =~ ^[1-9][0-9]*$ ]] || return 1
  opdracht="$(ps -o command= -p "$pid" 2>/dev/null)" || return 1
  [[ "$opdracht" =~ (^|[[:space:]/])brug[.]py[[:space:]]+luister([[:space:]]|$) ]]
}

# STOP komt niet altijd meteen aan: pas als ps toestand T toont, kan de luisteraar niets meer claimen.
staat_stil() {
  local pid="$1" stand poging
  for ((poging=0; poging<40; poging++)); do
    stand="$(/bin/ps -o stat= -p "$pid" 2>/dev/null)" || return 1
    [[ "$stand" =~ ^[[:space:]]*T ]] && return 0
    sleep 0.05
  done
  return 1
}

EINDE=$((SECONDS + 60))
OVERDRACHT_GESTART=0
GEPAUZEERDE_PID=""
hervat() {
  if [ -n "$GEPAUZEERDE_PID" ]; then
    kill -CONT "$GEPAUZEERDE_PID" 2>/dev/null || true
    GEPAUZEERDE_PID=""
  fi
}
trap 'hervat' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
while :; do
  IFS='|' read -r HUIDIGE_BRON HOOFD_PID RESERVE BEZIG WACHTRIJ <<< "$(toestand)"
  if [ "$HUIDIGE_BRON" = "sidecar" ]; then
    if [ "$OVERDRACHT_GESTART" = 1 ]; then
      echo "Oude luisteraar gestopt; sidecar heeft overgenomen"
    else
      echo "Sidecar draait"
    fi
    exit 0
  fi

  if [ "$RESERVE" = 1 ]; then
    if [ "$WACHT" = 0 ] || [ "$LAAT_STAAN" = 1 ]; then
      echo "Sidecar staat klaar als reserve en neemt over zodra de vorige luisteraar stopt"
      exit 0
    fi
    if [ "$HUIDIGE_BRON" = "terminal" ] && [ "$BEZIG" = 0 ] && [ "$WACHTRIJ" = 0 ] &&
       [ "$OVERDRACHT_GESTART" = 0 ]; then
      if ! is_luisteraar "$HOOFD_PID"; then
        echo "Sidecar staat klaar als reserve en neemt over zodra de vorige luisteraar stopt"
        exit 0
      fi
      GEPAUZEERDE_PID="$HOOFD_PID"
      if kill -STOP "$HOOFD_PID" 2>/dev/null && staat_stil "$HOOFD_PID"; then
        # Tijdens de pauze kan de luisteraar niets meer claimen of verplaatsen.
        IFS='|' read -r NIEUWE_BRON NIEUWE_PID NIEUWE_RESERVE NIEUW_BEZIG NIEUWE_WACHTRIJ <<< "$(toestand)"
        if [ "$NIEUWE_BRON" = "terminal" ] && [ "$NIEUWE_PID" = "$HOOFD_PID" ] &&
           [ "$NIEUWE_RESERVE" = 1 ] && [ "$NIEUW_BEZIG" = 0 ] &&
           [ "$NIEUWE_WACHTRIJ" = 0 ] && is_luisteraar "$HOOFD_PID"; then
          if kill -INT "$HOOFD_PID" 2>/dev/null; then
            OVERDRACHT_GESTART=1
          fi
        fi
      fi
      hervat
    fi
  fi

  if [ "$WACHT" = 0 ] || [ "$SECONDS" -ge "$EINDE" ]; then
    break
  fi
  sleep 0.5
done

if [ "$RESERVE" = 1 ]; then
  echo "Sidecar staat klaar als reserve en neemt over zodra de vorige luisteraar stopt"
else
  echo "Zet 'overleg-brug' aan in Antigravity: Automations"
fi
