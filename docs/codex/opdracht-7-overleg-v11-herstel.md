# Opdracht O3 - herstel overleg v1.1 na controle O2 (Codex maakt, Claude controleert)

Worktree `~/dev/_overleg-v11`, tak `overleg-v11`, commit 5818f67 (= v1.1 van Antigravity bovenop 82eda0e).
Lees eerst `CLAUDE.md` van de repo. Niet committen of pushen: Claude doet dat na controle.
Jouw eigen controle staat in `~/dev/samenwerking-codex/codex-O2-controle-overleg-v1.1.md`.

## Correctie op jouw punt 1 (gemeten door Claude)

De codes `MODEL_PLACEHOLDER_M410` t/m `M419` staan letterlijk in de Antigravity-binary
`/Applications/Antigravity.app/Contents/Resources/bin/language_server`: het zijn echte enumnamen van Antigravity,
geen verzonnen plaatshouders. Niet vervangen. Wel: zet bij `GEMINI_MODELLEN` (debat.py) een korte opmerking over die
herkomst, en dat de koppeling code -> model/niveau nog niet tegen de server bewezen is. Geen nieuwe codes verzinnen.

## Te herstellen (jouw punten 2-7)

2. **Hoog** - foutmeldingen van de Antigravity-server (`debat.py` rond 334, `overleg.py` rond 207): toon alleen
   methode en HTTP-code (en een korte, gezuiverde reden zonder headers, URL-query of tokenachtige waarden). Geen
   onbewerkte serverbody in runs/, rapport, dashboard of stderr. Test met een nep-antwoord dat een sleutel bevat.
3. **Middel** - `CLAUDE_CODE_OAUTH_TOKEN` (en `ANTIGRAVITY_CSRF_TOKEN`) alleen meegeven aan het kindproces dat hem
   nodig heeft: claude-token alleen naar claude, Antigravity-gegevens alleen naar agentapi. Codex krijgt geen van
   beide. Test dat.
4. **Middel** - weiger combinaties die niet exact uitvoerbaar zijn (bv. `-g flash_lite` met `-G high`) met een
   duidelijke melding vóór de eerste beurt, in plaats van stil iets anders te draaien.
5. **Middel** - een mislukte opruiming van een Gemini-sessie wordt zichtbaar (melding in stderr en in de
   beurt), niet stil genegeerd. Test de rechtstreekse opruimroute met een stub.
6. **Middel** - `-T` is één deadline per beurt vanaf het begin van die beurt, ook bij Gemini (starten + wachten).
7. **Laag** - `overleg.sh`: laat een geërfde `CLAUDE_MODEL` staan; eis `agentapi` alleen als de terugvalroute
   gebruikt wordt.
8. Haal de lege regel op het einde van het bestand weg die `git diff --check` meldt.

## Grenzen en afronding

Alleen bestanden in deze worktree. Geen netwerk, geen echte Codex-, Gemini- of Claude-oproep in tests, nooit de
echte `runs/` of `~/.gemini` aanraken. Haal nooit een sleutel uit processen, logs of de Keychain.
Draai daarna: `TMPDIR=$(mktemp -d) ~/dev/globaal-ai-debat/.venv/bin/python -m unittest test_grendels test_ronde
test_codex_sh test_meting test_overleg` en `git diff --check`, `bash -n overleg.sh`.

Antwoord kort in het Nederlands: per punt wat je deed (`bestand:regel`), de testuitslag, en wat open blijft.
