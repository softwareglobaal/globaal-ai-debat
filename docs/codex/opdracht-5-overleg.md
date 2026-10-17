# Opdracht O1 - overleg.sh vastzetten in globaal-ai-debat (Codex maakt, Claude controleert)

Datum 17-10-2026. Rolwissel tot ma 19-10 13:00: jij (Codex) schrijft, Claude controleert, commit en pusht.
Werkmap: deze worktree `~/dev/_overleg-vastzetten`, tak `overleg-vastzetten`, gebaseerd op origin/main (9165de3).
Lees eerst `CLAUDE.md` van de repo en volg die. Niet committen: Claude doet dat na controle.

## Stand

In deze worktree staan het driehoeksoverleg-gereedschap en de bijhorende wijzigingen, overgezet uit de gewone
checkout waar ze ongecommit stonden: nieuw `overleg.py` en `overleg.sh`, gewijzigd `debat.py` (roep_gemini via
Antigravity agentapi), `ronde.py`, `pagina.html`, `test_ronde.py`. Nulmeting: `python -m unittest test_grendels
test_ronde test_codex_sh test_meting` = 85 tests OK (2 skipped).

## Wat er mis ging (gemeten)

Op 17-10 om 10u21 startte een overleg vanuit een gewone terminal. Codex werkte 234 s, daarna faalde Gemini
meteen met `"ANTIGRAVITY_LS_ADDRESS is not set"`: de Gemini-toegang (adres + CSRF-token van de language server)
bestaat alleen in de Terminal van Antigravity. Het overleg was daardoor half en de Codex-beurt verspild.
Verder is de timeout per beurt vast 600 s (`draai_overleg(..., timeout=600)`), niet instelbaar via de CLI;
Codex op denkniveau ultra kan daarover gaan.

## Te doen

1. **Vroeg stoppen zonder Gemini-toegang.** Vóór de eerste beurt (dus vóór Codex start): als Gemini meedoet en
   `ANTIGRAVITY_LS_ADDRESS` leeg is, stop met exitcode 2 en een duidelijke Nederlandse melding
   ("start dit in de Terminal van Antigravity: Terminal > New Terminal"). Uitzondering alleen wanneer
   `GEMINI_AGENTAPI` uitdrukkelijk gezet is (teststub). Lees of kopieer NOOIT het CSRF-token of andere
   aanmeldgegevens uit het Antigravity-proces of zijn omgeving: het is een aanmeldsleutel.
   Geldt ook voor `overleg.sh --zelftest`.
2. **Timeout instelbaar.** `overleg.py -T/--timeout <seconden>` (geheel getal > 0, standaard 1200), doorgegeven
   aan Codex- en Gemini-beurten; `overleg.sh -T` geeft het door. Laat de korte startgrens in roep_gemini
   (`min(timeout, 30)` voor new-conversation) zoals ze is.
3. **Help en documentatie.** `overleg.sh --help`: noem -T en zeg eerlijk dat Gemini alleen werkt vanuit de
   Terminal van Antigravity. Voeg in `CLAUDE.md` of `README.md` (waar codex.sh beschreven staat) een korte
   paragraaf overleg.sh toe: doel, opties (-b, -m, -e, -g pro|flash|flash_lite, -T), waar het moet starten,
   `--verwerking` voor Claude's slotbeurt. Kort, Nederlands.
4. **Tests.** Nieuw `test_overleg.py`, draaiend op macOS, Linux en Windows (bash-delen overslaan op Windows):
   - zonder `ANTIGRAVITY_LS_ADDRESS` en zonder `GEMINI_AGENTAPI`: exitcode 2, de melding, en bewezen dat Codex
     NIET is aangeroepen;
   - `-T` komt aan in draai_overleg (en ongeldige waarden worden geweigerd);
   - één volledige ronde `-b 2` met een stub voor Codex en een stub-agentapi die een transcript schrijft
     (gebruik `GEMINI_AGENTAPI`, `GEMINI_BRAIN_DIR`, `--runs` naar een tijdelijke map): rapport bevat de
     gezamenlijke eindconclusie en het dashboard-board heeft codex/gemini/codex-beurten.
   Raak nooit de echte `runs/` of `~/.gemini` aan in tests.
5. **CI.** Voeg `test_overleg` toe aan de unittest-regel in `.github/workflows/grendels.yml`.
6. Draai daarna de volledige reeks met de venv van de gewone checkout (eigen TMPDIR):
   `TMPDIR=$(mktemp -d) ~/dev/globaal-ai-debat/.venv/bin/python -m unittest test_grendels test_ronde test_codex_sh test_meting test_overleg`.

## Grenzen

Alleen bestanden in deze worktree. Geen netwerk, geen push, geen commit. Geen echte Codex- of Gemini-oproep in
tests. Bestaande gedrag van codex.sh, ronde.py en het dashboard niet veranderen buiten wat hierboven staat.

## Antwoordvorm

Kort Nederlands: per punt 1-6 wat je deed (bestand:regel), de testuitslag (aantal, OK/fout), en wat je niet
kon of bewust anders deed.
