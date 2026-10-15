Opdracht 4 voor Codex, van Claude. 15-10-2026. Hercontrole van ronde 3.

Lees eerst de werkafspraken (hoogste versie) in `/Users/mehdichegini/TKN-buro Dropbox/private/0 Chegini Mehdi/Prive met Claude/`.
Jouw rol: nalezer. Alleen lezen: geen bestanden wijzigen, geen commits, geen netwerk.

Wat je nakijkt: deze repo op commit 0c2fb71 (main), vooral `git diff da2c152..0c2fb71`.
Jouw ronde 3: `docs/codex/codex-3-dashboard.md` (D13-D16). Claude's verwerking: `docs/codex/verwerkt-3-dashboard.md`.
Volgens Claude (beweringen, ga ze na): atomisch aanmaken via runs/.nieuw-* en rename; een beurt alleen in een ronde
die met een opdracht begint; de starter schrijft na setsid zijn groep naar een tijdelijk bestand en de val stopt
die groep; het slot met O_EXCL en een fstat/lstat-controle; een barrière in de slottest. 40 tests groen; CI groen op
macOS, Linux en Windows (run 38755362512, na een testherstel voor Windows in 0c2fb71); zelftest met de echte Codex
geslaagd; elke nieuwe test faalt op de foute code.

Let vooral op fouten in deze herstellingen: rename op Windows en bij een bestaande naam, achtergebleven
runs/.nieuw-*-mappen, het tijdelijke groepsbestand (opruimen, een oude waarde, de wachtlus van twee seconden in de
val), en of de nieuwe tests op Windows echt iets bewijzen of worden overgeslagen.

De tests kunnen in jouw sandbox niet draaien; lees dan de code.

Antwoord volgens de antwoordvorm in je vaste instructies: beslissing eerst, dan alleen nieuwe of nog openstaande
bevindingen vanaf D17, met ernst, bestand:regel, concreet voorbeeld en fix. Zeg per D13-D16 kort: hersteld of niet.
Hoogstens een pagina.
