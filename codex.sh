#!/bin/bash
# codex.sh v1.2 (15-10-2026) - de vaste manier waarop Claude Codex aanroept: `codex exec`.
# Elke ronde komt in het dashboard van ai-debat (http://127.0.0.1:8099, links bij de eerdere runs).
# De MCP-koppeling (`codex mcp-server`) bestaat niet meer sinds Codex 0.15x; niet terugzetten.
# Bron: repo softwareglobaal/globaal-ai-debat; ~/.claude/tools/codex.sh verwijst hierheen.
#
# Gebruik:
#   codex.sh -C <map> -o <rapport.md> [-t "<titel>"] [-s read-only|workspace-write] [-m model] [-e niveau]
#            [--met-config] [-- extra codex-vlaggen] < opdracht.md
#   codex.sh --verwerking <rapport.md> < verwerkt.md    Claude's verwerking als laatste beurt van die ronde
#   codex.sh --zelftest
#
# Standaard:
#   -s read-only        Codex leest en controleert, verandert niets. workspace-write alleen op een kopie.
#   -m / -e             model en redeneerniveau uit ~/.codex/config.toml (Mehdi's keuze in Codex).
#   -t                  titel in het dashboard; anders "Codex-controle: <map> - <rapport>".
#   zonder --met-config de config.toml wordt NIET geladen en apps + plugins staan uit: geen MCP-servers
#                       (geen toegang tot live systemen zoals contracten, post, pipedrive, en geen
#                       ChatGPT-apps zoals Drive, Agenda, IMAP), geen notify.
#   altijd              --ephemeral (geen sessie in de Codex-app), --skip-git-repo-check.
# Uitvoer: eindantwoord in <rapport.md> en op stdout, voortgang in <rapport.md>.log, rondenaam in
# <rapport.md>.ronde; de ronde zelf (opdracht, antwoord of fout, verwerking) in ~/dev/globaal-ai-debat/runs/.
# Foutcodes: 1 Codex faalde, 2 verkeerde invoer of voorwaarde, 3 antwoord niet in het dashboard, 130 onderbroken.
# Lange controles (minuten) vanuit Claude altijd met run_in_background starten.

set -u
CODEX="${CODEX_BIN:-/opt/homebrew/bin/codex}"
CONFIG="${CODEX_HOME:-$HOME/.codex}/config.toml"
AI_DEBAT="${AI_DEBAT:-$HOME/dev/globaal-ai-debat}"
RONDE="$AI_DEBAT/ronde.py"
PY="${CODEX_SH_PY:-$AI_DEBAT/.venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python3 || echo /opt/homebrew/bin/python3)"

fout() { echo "codex.sh: $*" >&2; exit 2; }

config_waarde() { # eerste top-level sleutel uit config.toml (voor de eerste [sectie])
  [ -f "$CONFIG" ] || return 0
  awk -v k="$1" '/^\[/{exit} $1==k && $2=="=" {sub(/^[^=]*= */,""); gsub(/"/,""); print; exit}' "$CONFIG"
}

ronde() { # ronde.py van ai-debat; CODEX_SH_RUNS geeft een andere runs-map (zelftest, tests)
  local extra=()
  [ -n "${CODEX_SH_RUNS:-}" ] && extra=(--runs "$CODEX_SH_RUNS")
  "$PY" "$RONDE" ${extra[@]+"${extra[@]}"} "$@"
}

dashboard_vooraf() { # grendel: zonder dashboard geen ronde
  [ -f "$RONDE" ] || fout "ronde.py niet gevonden in $AI_DEBAT (repo softwareglobaal/globaal-ai-debat)"
  [ -x "$PY" ] || fout "geen python voor ronde.py ($PY)"
}

controle_vooraf() { # grendel: faalt duidelijk als een Codex-update de afspraak breekt
  [ -x "$CODEX" ] || fout "Codex niet gevonden op $CODEX (brew install --cask codex)"
  local hulp; hulp="$("$CODEX" exec --help 2>&1)" || fout "'codex exec' werkt niet: $("$CODEX" --version 2>&1)"
  local v
  for v in --sandbox --model --cd --output-last-message --skip-git-repo-check --ephemeral --ignore-user-config --config --disable; do
    printf '%s' "$hulp" | grep -q -- "$v" || fout "codex exec kent $v niet meer ($("$CODEX" --version 2>&1)); script aanpassen"
  done
  "$CODEX" login status 2>&1 | grep -q -i 'logged in' || fout "Codex is niet ingelogd: Mehdi doet 'codex login' in Terminal"
  dashboard_vooraf
}

waarde() { [ "$1" -ge 2 ] || fout "$2 vraagt een waarde (zie --help)"; }

MAP="" RAPPORT="" TITEL="" SANDBOX="read-only" MODEL="" NIVEAU="" METCONFIG=0 ZELFTEST=0 VERWERK=""
while [ $# -gt 0 ]; do
  case "$1" in
    -C) waarde $# "$1"; MAP="$2"; shift 2 ;;
    -o) waarde $# "$1"; RAPPORT="$2"; shift 2 ;;
    -t) waarde $# "$1"; TITEL="$2"; shift 2 ;;
    -s) waarde $# "$1"; SANDBOX="$2"; shift 2 ;;
    -m) waarde $# "$1"; MODEL="$2"; shift 2 ;;
    -e) waarde $# "$1"; NIVEAU="$2"; shift 2 ;;
    --verwerking) waarde $# "$1"; VERWERK="$2"; shift 2 ;;
    --met-config) METCONFIG=1; shift ;;
    --zelftest) ZELFTEST=1; shift ;;
    --) shift; break ;;
    -h|--help) awk 'NR>1 && /^#/ {sub(/^# ?/,""); print; next} NR>1 {exit}' "$0"; exit 0 ;;
    *) fout "onbekende optie: $1 (zie --help)" ;;
  esac
done

if [ -n "$VERWERK" ]; then
  dashboard_vooraf
  if [ -f "$VERWERK.ronde" ]; then RUN="$(cat "$VERWERK.ronde")"; else RUN="$VERWERK"; fi
  [ -t 0 ] && fout "geef de verwerking via stdin (< verwerkt.md)"
  ronde beurt "$RUN" --kant claude --soort verwerking >/dev/null || fout "verwerking niet toegevoegd aan ronde $RUN"
  echo "verwerking toegevoegd aan ronde $RUN (dashboard http://127.0.0.1:8099)"
  exit 0
fi

controle_vooraf
[ -n "$MODEL" ] || MODEL="$(config_waarde model)"
[ -n "$NIVEAU" ] || NIVEAU="$(config_waarde model_reasoning_effort)"

if [ "$ZELFTEST" = 1 ]; then
  T="$(mktemp -d "${TMPDIR:-/tmp}/codex-zelftest.XXXXXX")"
  echo "Antwoord met precies een woord: KLAAR" \
    | CODEX_SH_RUNS="$T/runs" "$0" -C "$T" -o "$T/antwoord.md" -t "zelftest" -e low >/dev/null 2>&1
  [ "$(tr -d '[:space:]' < "$T/antwoord.md" 2>/dev/null)" = "KLAAR" ] \
    || { echo "zelftest MISLUKT (Codex), log: $T/antwoord.md.log" >&2; exit 1; }
  echo "zelftest verwerkt" | CODEX_SH_RUNS="$T/runs" "$0" --verwerking "$T/antwoord.md" >/dev/null 2>&1
  B="$T/runs/$(cat "$T/antwoord.md.ronde" 2>/dev/null)/board.jsonl"
  SOORTEN="$(grep -o '"soort": "[a-z]*"' "$B" 2>/dev/null | tr -d '\n')"
  [ "$SOORTEN" = '"soort": "opdracht""soort": "controle""soort": "verwerking"' ] \
    || { echo "zelftest MISLUKT (dashboard): $B" >&2; exit 1; }
  echo "zelftest geslaagd: $("$CODEX" --version 2>&1), model ${MODEL:-standaard}, dashboard-ronde opdracht+controle+verwerking"
  exit 0
fi

[ -n "$MAP" ] && [ -d "$MAP" ] || fout "-C <map> ontbreekt of bestaat niet"
[ -n "$RAPPORT" ] || fout "-o <rapport.md> ontbreekt"
mkdir -p "$(dirname "$RAPPORT")" || fout "kan $(dirname "$RAPPORT") niet aanmaken"
case "$SANDBOX" in read-only|workspace-write) ;; *) fout "-s moet read-only of workspace-write zijn" ;; esac
[ -t 0 ] && fout "geef de opdracht via stdin (< opdracht.md of een heredoc)"
OPDRACHT="$(cat)"; [ -n "$OPDRACHT" ] || fout "opdracht is leeg"
[ -n "$TITEL" ] || TITEL="Codex-controle: $(basename "$MAP") - $(basename "$RAPPORT" .md)"

START=$SECONDS
RUN="$(printf '%s\n' "$OPDRACHT" | ronde nieuw --titel "$TITEL" --map "$MAP" --rapport "$RAPPORT" \
        --model "$MODEL" --niveau "$NIVEAU" --sandbox "$SANDBOX")" || fout "kon de ronde niet in het dashboard zetten"
printf '%s\n' "$RUN" > "$RAPPORT.ronde"

# Onderbroken (Ctrl-C, kill, sessie gestopt): Codex stoppen en de ronde als fout markeren, niet half laten staan.
CPID="" AFGESLOTEN=0
onderbroken() {
  trap - INT TERM HUP
  [ -n "$CPID" ] && kill "$CPID" 2>/dev/null
  if [ "$AFGESLOTEN" = 0 ]; then
    echo "Onderbroken door een signaal na $((SECONDS - START)) s; Codex gaf geen antwoord." \
      | ronde beurt "$RUN" --kant codex --soort fout --model "$MODEL" --duur "$((SECONDS - START))" >/dev/null 2>&1
  fi
  echo "codex.sh: onderbroken; ronde $RUN staat als fout in het dashboard" >&2
  exit 130
}
trap onderbroken INT TERM HUP

ARGS=(exec --ephemeral --skip-git-repo-check -s "$SANDBOX" -C "$MAP" -o "$RAPPORT")
[ "$METCONFIG" = 1 ] || ARGS+=(--ignore-user-config --disable apps --disable plugins)
[ -n "$MODEL" ] && ARGS+=(-m "$MODEL")
[ -n "$NIVEAU" ] && ARGS+=(-c "model_reasoning_effort=\"$NIVEAU\"")
[ $# -gt 0 ] && ARGS+=("$@")

# Op de achtergrond met wait, zodat een signaal meteen de val hierboven bereikt.
printf '%s\n' "$OPDRACHT" | "$CODEX" "${ARGS[@]}" - > "$RAPPORT.log" 2>&1 &
CPID=$!
wait "$CPID"
CODE=$?
CPID=""
DUUR=$((SECONDS - START))
if [ $CODE -ne 0 ] || [ ! -s "$RAPPORT" ]; then
  { echo "Codex stopte met code $CODE. Laatste regels van het log:"; echo; tail -20 "$RAPPORT.log"; } \
    | ronde beurt "$RUN" --kant codex --soort fout --model "$MODEL" --duur "$DUUR" >/dev/null
  AFGESLOTEN=1
  echo "codex.sh: Codex stopte met code $CODE; laatste regels van $RAPPORT.log:" >&2
  tail -20 "$RAPPORT.log" >&2
  exit 1
fi
if ! ronde beurt "$RUN" --kant codex --soort controle --model "$MODEL" --duur "$DUUR" < "$RAPPORT" >/dev/null; then
  AFGESLOTEN=1
  cat "$RAPPORT"
  echo "codex.sh: het antwoord staat in $RAPPORT maar NIET in het dashboard (ronde $RUN)" >&2
  exit 3
fi
AFGESLOTEN=1
cat "$RAPPORT"
echo "codex.sh: ronde $RUN staat in het dashboard (http://127.0.0.1:8099)" >&2
