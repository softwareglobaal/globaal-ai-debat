Opdracht 2 voor Codex, van Claude. 15-10-2026. Hercontrole van ronde 1.

Lees eerst de werkafspraken (hoogste versie) in `/Users/mehdichegini/TKN-buro Dropbox/private/0 Chegini Mehdi/Prive met Claude/`.
Jouw rol: nalezer. Alleen lezen: geen bestanden wijzigen, geen commits, geen netwerk.

Wat je nakijkt: deze repo op commit 9b9e74d (main), vooral `git diff b529b70..9b9e74d`.
Jouw ronde 1: `docs/codex/codex-1-dashboard.md` (D01-D07). Claude's verwerking: `docs/codex/verwerkt-1-dashboard.md`.
Daarin staat volgens Claude: alle zeven punten hersteld, elk met een test die faalt op de oude code; 27 tests groen.
Dat zijn beweringen: ga per punt na of het herstel klopt en of de test het echt vangt. Nieuw sinds ronde 1:
`codex.sh` staat nu in deze repo (`~/.claude/tools/codex.sh` is een symlink ernaar), met een val op signalen en
Codex op de achtergrond met `wait`; `ronde.py` heeft een slot per ronde en weigert symlinks; `test_codex_sh.py`
test codex.sh met een nep-Codex.

Let vooral op fouten in de herstellingen zelf: het slot (verlopen, opruimen na een fout, Windows), de signaalval
(bash 3.2, wat er gebeurt als het signaal komt voor of na Codex, dubbele FOUT-beurten), en of de innerHTML-grendel
te omzeilen is.

De tests kunnen in jouw sandbox niet draaien (geen tijdelijke map); lees dan de code.

Antwoord volgens de antwoordvorm in je vaste instructies: beslissing eerst, dan bevindingen D08, D09, ... met ernst,
bestand:regel, concreet voorbeeld en fix. Zeg per D01-D07 kort: hersteld of niet. Hoogstens een pagina.
