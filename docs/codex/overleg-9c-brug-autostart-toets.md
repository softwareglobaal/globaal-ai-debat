# Driehoeksoverleg (Codex, Gemini & Claude): O9c brug autostart: derde toets 2-op-3
Ronde in dashboard: `20261017-170859-codex` (http://127.0.0.1:8099)
Modellen en denkstand:
- Claude: `claude-opus-5-5` (denkstand: `xhigh`)
- Codex: `gpt-6-sol` (denkstand: `ultra`)
- Gemini (Antigravity): `Gemini 4 Argon (High)` (`gemini-4-argon`, denkstand: `high`)

## OVERLEG (Codex) (gpt-6-sol · ultra, 142.2s)

**NO-GO, voorlopige stem van Codex: 1 tegen.** De stemmen van Claude en Gemini over O9c ontbreken nog; er is dus nog geen 2-op-3-besluit.

1. **MIDDEL.** De overname is verbeterd, maar het installatiescript controleert niet of de oude luisteraar na `STOP` werkelijk stilstaat. Claimt die nog net een overleg, dan kan de overname het afbreken. De gerichte test plaatst een taak tijdens de pauze, maar toetst vertraagde levering van `STOP` niet.  
   Techniek voor Claude: [installeer_sidecar.sh:157](/Users/mehdichegini/dev/_codex-brug-autostart/installeer_sidecar.sh:157), [test_brug.py:1060](/Users/mehdichegini/dev/_codex-brug-autostart/test_brug.py:1060) - bevestig eerst processtatus `T`, controleer daarna de mappen opnieuw en test vertraagde stop.

2. **HOOG.** De webstop stuurt geen signaal meer naar een opgeruimd proces. De brug doet dat bij het opruimen van een overleg nog wel: na `communicate()` kan de leider al zijn opgeruimd, waarna alsnog `SIGKILL` naar zijn oude groepsnummer gaat. Bij hergebruik kan dat een ander proces raken. Dit is een overgebleven fout in de stoproute, geen nieuwe fout van O9c.  
   Techniek voor Claude: [brug.py:430](/Users/mehdichegini/dev/_codex-brug-autostart/brug.py:430) - houd de leider tot na het laatste groepssignaal onopgeruimd; voeg een gerichte test toe.

**Wel aangetoond in code en gerichte tests:** herstel bewaart een geldige eindstatus en sluit verweesde taken af; beide tokenroutes beperken het adres en schakelen proxy en omleiding uit. De gemelde 162 geslaagde tests en 30 herhalingen heb ik tijdens deze leescontrole niet opnieuw uitgevoerd.

Gedaan: alleen gelezen.  
Nagekeken: vier eerdere blokkades, herstelcode en gerichte tests.  
Open: twee punten boven oplossen en onafhankelijk toetsen vóór livegang.

## OVERLEG (Gemini) (Gemini 4 Argon (High), 764.8s)

**NO-GO (voorlopig 2-0 met Codex; 2-op-3 meerderheid bereikt, Claude stemt hierna).**

Ik ben het volledig eens met de analyse en beide blokkades van Codex. Daarmee is er een 2-op-3 meerderheid om deze twee punten eerst te herstellen en te testen voor we naar `main` pushen. Mehdi hoeft hier niet tussen te komen.

### Toets van de vier eerdere punten (A) en openstaande blokkades (B)

Punten 2 en 3 uit O9b zijn volledig opgelost en met tests bewezen: een geschreven eindstatus in `bezig/` blijft na een crash behouden ([brug.py:473-498](file:///Users/mehdichegini/dev/_codex-brug-autostart/brug.py#L473-L498)), een wachtende indiener sluit verweesde taken zelf af zodra het slot vrij is ([brug.py:386-396](file:///Users/mehdichegini/dev/_codex-brug-autostart/brug.py#L386-L396)), en het token gaat in beide routes uitsluitend nog naar gecontroleerde loopback-adressen zonder proxy of HTTP-omleiding ([brug.py:297-328](file:///Users/mehdichegini/dev/_codex-brug-autostart/brug.py#L297-L328), [debat.py:361-391](file:///Users/mehdichegini/dev/_codex-brug-autostart/debat.py#L361-L391)). Er zijn geen nieuwe fouten door O9c geïntroduceerd.

Op punten 1 en 4 resten nog twee open punten (één HOOG, één MIDDEL):

1. **HOOG - Stoppen van een overleg in de brug stuurt alsnog een hard stopsignaal naar een al opgeruimd groepsnummer.**  
   In de webapp (`debat.stop_proces` en `web.py`) is de procesrace netjes gedicht, maar in de brug zelf nog niet. Wanneer `overleg.py` bij het stoppen van de luisteraar of bij een tijdslimiet netjes binnen 7 seconden stopt na `SIGTERM`, ruimt `proces.communicate(timeout=7)` de procesleider direct op (`waitpid`). Het groepsnummer is dan vrijgegeven, maar vier regels lager stuurt de brug alsnog onvoorwaardelijk `SIGKILL` naar dat oude groepsnummer. In de praktijk kan dat op een drukke Mac een willekeurig ander proces raken.  
   Techniek voor Claude: [brug.py:430-445](file:///Users/mehdichegini/dev/_codex-brug-autostart/brug.py#L430-L445) - houd de procesleider onopgeruimd tot na het laatste `os.killpg(proces.pid, signal.SIGKILL)` (of voorkom dat `communicate` de leider al vóór `SIGKILL` reapt) en voeg een gerichte test toe dat na het opruimen van de leider geen `killpg` meer volgt.

2. **MIDDEL - Het installatiescript wacht na `STOP` niet aantoonbaar tot de oude luisteraar echt stilstaat.**  
   Het stopsignaal in `brug.py` onderbreekt geen bestandswissels meer, maar `installeer_sidecar.sh` leest na `kill -STOP` meteen de mappen uit zonder eerst te verifiëren dat het proces daadwerkelijk de gestopte status (`T`) heeft bereikt. Als `STOP` op een andere CPU-kern een fractie vertraagd aankomt, kan een net aangenomen overleg alsnog worden afgebroken.  
   Techniek voor Claude: [installeer_sidecar.sh:158-169](file:///Users/mehdichegini/dev/_codex-brug-autostart/installeer_sidecar.sh#L158-L169), [test_brug.py:1060-1116](file:///Users/mehdichegini/dev/_codex-brug-autostart/test_brug.py#L1060-L1116) - wacht na `kill -STOP` eerst tot `ps -o stat= -p "$HOOFD_PID"` met `T` begint, controleer pas daarna `toestand` opnieuw, en test een vertraagde aankomst van `STOP`.

Geen open punten van ernst LAAG.

## Gezamenlijke Eindconclusie — CONTROLE (Codex) (gpt-6-sol · ultra, 30.1s)

**NO-GO.** Codex en Gemini stemmen tegen livegang. Dat zijn twee van de drie vereiste stemmen; Claudes stem ontbreekt nog, dus een uitslag van 3-0 of 2-1 kan ik niet eerlijk vermelden. De brug gaat nu niet naar `main`.

## Voor Mehdi

De automatische overname kan nog een overleg afbreken als de oude luisteraar een taak aanneemt vlak voordat hij werkelijk stilstaat. Het installatiescript moet eerst bevestigen dat hij gestopt is en pas dan opnieuw controleren of er geen werk loopt.

Bij het stoppen van een overleg kan de brug nog een hard stopsignaal naar een inmiddels vrijgegeven procesgroep sturen. Daardoor kan in het slechtste geval een ander proces geraakt worden. We herstellen de volgorde van stoppen en opruimen en testen die situatie gericht.

Het bewaren van een einduitslag na een crash en het afschermen van het toegangstoken zijn volgens de aangeleverde code en tests opgelost. Voor de twee open punten is geen zakelijke keuze van Mehdi nodig.

## Voor Claude en Shaniel

1. **HOOG, 2-0 vastgesteld:** `brug.py:430-445` - houd de procesleider tot ná het laatste `killpg` onopgeruimd; test dat na vrijgave van zijn groepsnummer geen groepssignaal volgt.
2. **MIDDEL, 2-0 vastgesteld:** `installeer_sidecar.sh:157-169`, `test_brug.py:1060-1116` - wacht na `STOP` op processtatus `T`, controleer daarna de mappen opnieuw en test vertraagde levering van `STOP`.

Gedaan: gezamenlijke conclusie op basis van de twee beschikbare stemmen.  
Nagekeken: vier eerdere blokkades en de gemelde testuitslagen.  
Open: twee herstelpunten en hun gerichte tests vóór livegang.
