Opdracht 3 voor Codex, van Claude. 15-10-2026. Hercontrole van ronde 2.

Lees eerst de werkafspraken (hoogste versie) in `/Users/mehdichegini/TKN-buro Dropbox/private/0 Chegini Mehdi/Prive met Claude/`.
Jouw rol: nalezer. Alleen lezen: geen bestanden wijzigen, geen commits, geen netwerk.

Wat je nakijkt: deze repo op commit da2c152 (main), vooral `git diff 9b9e74d..da2c152`.
Jouw ronde 2: `docs/codex/codex-2-dashboard.md` (D08-D12 en de rest van D03, D05, D07).
Claude's verwerking: `docs/codex/verwerkt-2-dashboard.md`. Volgens Claude (beweringen, ga ze na): alles hersteld met
een OS-slot (flock/msvcrt), een uitkomst per ronde in ronde.py, de signaalval vóór het aanmaken met --naambestand,
Codex in een eigen procesgroep via setsid, een strengere HTML-grendel; 36 tests groen; CI groen op macOS, Linux
en Windows (run 38753120119); elke nieuwe test faalt op de foute code; live weergave met kwaadaardige namen veilig.

Let vooral op fouten in deze herstellingen: het OS-slot op elk systeem (msvcrt-lengte, fd-lekken, O_NOFOLLOW),
de val in codex.sh (`$!` vóór en na de start, de setsid-aanroep, exitcodes), de testhaak `_NA_LEZEN` (mag niet
in gewoon gebruik meespelen), en of de signaaltests betrouwbaar zijn of soms per toeval slagen.

De tests kunnen in jouw sandbox niet draaien; lees dan de code.

Antwoord volgens de antwoordvorm in je vaste instructies: beslissing eerst, dan alleen nieuwe of nog openstaande
bevindingen vanaf D13, met ernst, bestand:regel, concreet voorbeeld en fix. Zeg per D08-D12 kort: hersteld of niet.
Hoogstens een pagina.
