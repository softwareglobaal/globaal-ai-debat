#!/bin/bash
# overleg.sh v1.1 (17-10-2026) - de vaste manier waarop Claude, Codex EN Gemini samen in overleg gaan.
# Elke ronde komt met alle tussenbeurten in het dashboard van ai-debat (http://127.0.0.1:8099).
# Bron: repo softwareglobaal/globaal-ai-debat; ~/.claude/tools/overleg.sh verwijst hierheen.
#
# Gebruik:
#   overleg.sh -C <map> -o <rapport.md> [-t "<titel>"] [-b <diepte>]
#              [-m codex-model] [-e codex-niveau]
#              [-g gemini-model] [-G gemini-niveau]
#              [-c claude-model] [-E claude-niveau] [--met-claude]
#              [-T seconden] < opdracht.md
#   overleg.sh --verwerking <rapport.md> < verwerkt.md    Claude's verwerking als laatste beurt van die ronde
#   overleg.sh --zelftest
#   Gemini werkt alleen vanuit de Terminal van Antigravity (Terminal > New Terminal): de toegang komt uit die terminal, niet uit de app.
#
# Standaard:
#   -b 2                Codex analyseert -> Gemini analyseert + vult aan/corrigeert -> Codex trekt gezamenlijke eindconclusie.
#   Beide adviseurs lezen alleen en wijzigen niets.
#   -m / -e             Standaard uit ~/.codex/config.toml (bijv. gpt-6-sol / ultra of xhigh).
#   -g gemini-4-argon   Gemini 4 Argon via lokale Antigravity LanguageServerService (ook: gemini-3.8-flash, pro, flash).
#   -G high             Gemini denkniveau: high, medium of low (zonder -G: high, bij flash_lite low).
#   -c / -E             Claude-model en denkniveau (max, xhigh, high, medium, low); standaard uit actieve Claude-sessie.
#   --met-claude        Laat Claude ook zelfstandig een overlegbeurt draaien via de CLI.
#   -T 1200             Timeout per beurt, in seconden (> 0).
# Uitvoer: volledig verslag + gezamenlijke eindconclusie in <rapport.md> en op stdout, rondenaam in <rapport.md>.ronde,
# en alle beurten live in ~/dev/globaal-ai-debat/runs/.

set -u
AI_DEBAT="${AI_DEBAT:-$HOME/dev/globaal-ai-debat}"
OVERLEG="$AI_DEBAT/overleg.py"
RONDE="$AI_DEBAT/ronde.py"
CODEX_SH="$AI_DEBAT/codex.sh"
PY="${CODEX_SH_PY:-$AI_DEBAT/.venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python3 || echo /opt/homebrew/bin/python3)"
AGENTAPI="${GEMINI_AGENTAPI:-$HOME/.gemini/antigravity/bin/agentapi}"

fout() { echo "overleg.sh: $*" >&2; exit 2; }

waarde() { [ "$1" -ge 2 ] || fout "$2 vraagt een waarde (zie --help)"; }

MAP="" RAPPORT="" TITEL="" DIEPTE="2" MODEL="" NIVEAU=""
GEMINI="gemini-4-argon" GEMINI_NIVEAU=""
CLAUDE_MODEL="${CLAUDE_MODEL:-}" CLAUDE_NIVEAU="" MET_CLAUDE=0
TIMEOUT="1200" ZELFTEST=0 VERWERK=""
while [ $# -gt 0 ]; do
  case "$1" in
    -C) waarde $# "$1"; MAP="$2"; shift 2 ;;
    -o) waarde $# "$1"; RAPPORT="$2"; shift 2 ;;
    -t) waarde $# "$1"; TITEL="$2"; shift 2 ;;
    -b) waarde $# "$1"; DIEPTE="$2"; shift 2 ;;
    -m) waarde $# "$1"; MODEL="$2"; shift 2 ;;
    -e) waarde $# "$1"; NIVEAU="$2"; shift 2 ;;
    -g) waarde $# "$1"; GEMINI="$2"; shift 2 ;;
    -G|--gemini-niveau) waarde $# "$1"; GEMINI_NIVEAU="$2"; shift 2 ;;
    -c|--claude-model) waarde $# "$1"; CLAUDE_MODEL="$2"; shift 2 ;;
    -E|--claude-niveau) waarde $# "$1"; CLAUDE_NIVEAU="$2"; shift 2 ;;
    --met-claude) MET_CLAUDE=1; shift ;;
    -T|--timeout) waarde $# "$1"; TIMEOUT="$2"; shift 2 ;;
    --verwerking) waarde $# "$1"; VERWERK="$2"; shift 2 ;;
    --zelftest) ZELFTEST=1; shift ;;
    -h|--help) awk 'NR>1 && /^#/ {sub(/^# ?/,""); print; next} NR>1 {exit}' "$0"; exit 0 ;;
    *) fout "onbekende optie: $1 (zie --help)" ;;
  esac
done

[ -f "$OVERLEG" ] || fout "overleg.py niet gevonden in $AI_DEBAT"
[ -f "$RONDE" ] || fout "ronde.py niet gevonden in $AI_DEBAT"
[ -x "$PY" ] || fout "geen python gevonden ($PY)"

if [ -n "$VERWERK" ]; then
  exec "$CODEX_SH" --verwerking "$VERWERK"
fi

if ! [[ "${ANTIGRAVITY_LS_ADDRESS:-}" =~ [^[:space:]] ]] || ! [[ "${ANTIGRAVITY_CSRF_TOKEN:-}" =~ [^[:space:]] ]]; then
  if ! [[ "${GEMINI_AGENTAPI:-}" =~ [^[:space:]] ]]; then
    if [ -z "${GEMINI_BRAIN_DIR:-}" ] && [ -f "$AI_DEBAT/brug.py" ] \
       && "$PY" -c "import sys; sys.path.insert(0, '$AI_DEBAT'); import brug; sys.exit(0 if brug.brug_leeft(brug.brugmap()) else 1)" 2>/dev/null; then
      if [ "$ZELFTEST" = 1 ]; then
        mkdir -p "$HOME/.overleg-brug"
        T="$(mktemp -d "$HOME/.overleg-brug/zelftest.XXXXXX")"
        trap 'rm -rf "$T"' EXIT
        echo "Antwoord met precies een woord: KLAAR" \
          | "$0" -C "$T" -o "$T/antwoord.md" -t "zelftest-overleg" -b 1 -e low -g gemini-3.8-flash -G low -T "$TIMEOUT" >/dev/null 2>&1 \
          || { echo "zelftest MISLUKT (overleg)" >&2; exit 1; }
        echo "zelftest verwerkt" | "$0" --verwerking "$T/antwoord.md" >/dev/null 2>&1 \
          || { echo "zelftest MISLUKT (verwerking)" >&2; exit 1; }
        echo "zelftest geslaagd: Codex + Gemini + Claude verwerking in dashboard"
        exit 0
      fi
      [ -n "$MAP" ] && [ -d "$MAP" ] || fout "-C <map> ontbreekt of bestaat niet"
      [ -n "$RAPPORT" ] || fout "-o <rapport.md> ontbreekt"
      [ -t 0 ] && fout "geef de opdracht via stdin (< opdracht.md of een heredoc)"
      BRUG_ARGS=(-C "$MAP" -o "$RAPPORT" -t "${TITEL:-Overleg}" -b "$DIEPTE" -g "$GEMINI" -T "$TIMEOUT" --wacht)
      [ -n "$MODEL" ] && BRUG_ARGS+=(-m "$MODEL")
      [ -n "$NIVEAU" ] && BRUG_ARGS+=(-e "$NIVEAU")
      [ -n "$GEMINI_NIVEAU" ] && BRUG_ARGS+=(-G "$GEMINI_NIVEAU")
      [ -n "$CLAUDE_MODEL" ] && BRUG_ARGS+=(-c "$CLAUDE_MODEL")
      [ -n "$CLAUDE_NIVEAU" ] && BRUG_ARGS+=(-E "$CLAUDE_NIVEAU")
      [ "$MET_CLAUDE" = 1 ] && BRUG_ARGS+=(--met-claude)
      "$PY" "$AI_DEBAT/brug.py" indienen "${BRUG_ARGS[@]}" >/dev/null && cat "$RAPPORT"
      exit $?
    fi
    fout "Gemini-toegang ontbreekt; start dit in de Terminal van Antigravity: Terminal > New Terminal"
  fi
fi

if [[ "${GEMINI_AGENTAPI:-}" =~ [^[:space:]] ]] || [[ "${GEMINI_BRAIN_DIR:-}" =~ [^[:space:]] ]] \
   || ! [[ "${ANTIGRAVITY_LS_ADDRESS:-}" =~ [^[:space:]] ]] \
   || ! [[ "${ANTIGRAVITY_CSRF_TOKEN:-}" =~ [^[:space:]] ]]; then
  [ -x "$AGENTAPI" ] || fout "Gemini agentapi niet gevonden op $AGENTAPI (is Antigravity geinstalleerd?)"
fi

if [ "$ZELFTEST" = 1 ]; then
  T="$(mktemp -d "${TMPDIR:-/tmp}/overleg-zelftest.XXXXXX")"
  trap 'rm -rf "$T"' EXIT
  echo "Antwoord met precies een woord: KLAAR" \
    | CODEX_SH_RUNS="$T/runs" "$0" -C "$T" -o "$T/antwoord.md" -t "zelftest-overleg" -b 1 -e low -g gemini-3.8-flash -G low -T "$TIMEOUT" >/dev/null 2>&1 \
    || { echo "zelftest MISLUKT (overleg)" >&2; exit 1; }
  echo "zelftest verwerkt" | CODEX_SH_RUNS="$T/runs" "$0" --verwerking "$T/antwoord.md" >/dev/null 2>&1 \
    || { echo "zelftest MISLUKT (verwerking)" >&2; exit 1; }
  echo "zelftest geslaagd: Codex + Gemini + Claude verwerking in dashboard"
  exit 0
fi

[ -n "$MAP" ] && [ -d "$MAP" ] || fout "-C <map> ontbreekt of bestaat niet"
[ -n "$RAPPORT" ] || fout "-o <rapport.md> ontbreekt"
[ -t 0 ] && fout "geef de opdracht via stdin (< opdracht.md of een heredoc)"

EXTRA=()
[ -n "${CODEX_SH_RUNS:-}" ] && EXTRA+=(--runs "$CODEX_SH_RUNS")
[ -n "$TITEL" ] && EXTRA+=(-t "$TITEL")
[ -n "$MODEL" ] && EXTRA+=(-m "$MODEL")
[ -n "$NIVEAU" ] && EXTRA+=(-e "$NIVEAU")
[ -n "$GEMINI_NIVEAU" ] && EXTRA+=(-G "$GEMINI_NIVEAU")
[ -n "$CLAUDE_MODEL" ] && EXTRA+=(-c "$CLAUDE_MODEL")
[ -n "$CLAUDE_NIVEAU" ] && EXTRA+=(-E "$CLAUDE_NIVEAU")
[ "$MET_CLAUDE" = 1 ] && EXTRA+=(--met-claude)

exec "$PY" "$OVERLEG" -C "$MAP" -o "$RAPPORT" -b "$DIEPTE" -g "$GEMINI" -T "$TIMEOUT" ${EXTRA[@]+"${EXTRA[@]}"}
