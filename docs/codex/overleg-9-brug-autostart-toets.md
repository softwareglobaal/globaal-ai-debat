# Driehoeksoverleg (Codex, Gemini & Claude): O9 brug autostart: toets 2-op-3
Ronde in dashboard: `20261017-160743-codex` (http://127.0.0.1:8099)
Modellen en denkstand:
- Claude: `claude-opus-5-5` (denkstand: `xhigh`)
- Codex: `gpt-6-sol` (denkstand: `ultra`)
- Gemini (Antigravity): `Gemini 4 Argon (High)` (`gemini-4-argon`, denkstand: `high`)

## OVERLEG (Codex) (gpt-6-sol · ultra, 212.1s)

**NO-GO. Codex stemt tegen livegang; de stemmen van Claude en Gemini zijn mij nog niet bekend.** Het luisterslot voorkomt dat twee luisteraars tegelijk opdrachten claimen. Ik zie wel twee fouten waardoor een overleg tijdens de overdracht verkeerd kan aflopen.

1. Bij exitcode 3 stopt de brug een lopend overleg, maar een Codex- of Claude-proces kan blijven draaien. De nieuwe luisteraar kan dan al een volgende opdracht starten terwijl de vorige nog werkt.  
   Techniek voor Claude: `brug.py:357-372,396-398` en `debat.py:276-280` - volg en stop ook de afzonderlijke kindprocesgroepen; wacht daarop vóór het luisterslot vrijkomt. Test dit met een kind in een eigen procesgroep.

2. Bij overname verdwijnt de hartslag voordat de reserve het slot krijgt. Een indiener die op antwoord wacht, krijgt dan een fout terwijl zijn opdracht in de wachtrij blijft en later alsnog kan draaien. Mehdi kan daardoor opnieuw indienen en twee overleggen krijgen.  
   Techniek voor Claude: `brug.py:331-333,562,602-606` - laat `--wacht` de overdracht overbruggen en geef een aangenomen opdracht pas als mislukt terug wanneer vaststaat dat zij niet later wordt uitgevoerd. Test de overdracht met een wachtende indiener.

Het sidecar-manifest bevat de gevraagde startopties en `restart_policy: always` (`installeer_sidecar.sh:51-56`). De nieuwe tests bewijzen doorsturen en exitcode 2 zonder levende brug, maar simuleren geen overdracht of lopend echt kindproces (`test_overleg.py:508-534,574-609`). Ik zie in de nieuwe hartslag en meldingen geen directe opname van adres of token.

Gedaan: code en tests alleen gelezen.  
Nagekeken: slot, exit 3, geheimen, sidecar en doorsturen.  
Open: beide blokkerende fouten herstellen en gericht testen; daarna opnieuw stemmen.

## OVERLEG (Gemini) (Gemini 4 Argon (High), 157.7s)

**NO-GO (2-0 meerderheid met Codex tegen livegang; eerst drie blokkerende fouten rond afbreken en overdracht oplossen).**

Ik ben het eens met beide blokkerende punten van Codex en voeg daar een derde blokkerend punt aan toe dat ik in de code vond: wat er gebeurt als Antigravity de sidecar herstart met een normaal stopsignaal (`SIGTERM`) en bij een eenmalige hapering van de verbindingstoets.

1. **Oude overlegprocessen draaien door na afbreken of herstart (twee opdrachten tegelijk mogelijk):**
Codex zag terecht dat `debat.py` elk Codex- en Claude-proces in een eigen procesgroep start, waardoor de brug bij afbreken alleen de hoofdgroep stopt en kinderen laat doordraaien. Daar komt bij dat `brug.py` alleen `Ctrl-C` (`SIGINT`) opvangt en geen normaal stopsignaal (`SIGTERM`). Als Antigravity de sidecar stopt of herstart, valt `brug.py` direct weg zonder zijn opruimblok uit te voeren: het lopende overleg blijft op de achtergrond draaien terwijl de nieuwe luisteraar al een volgende opdracht start, en de afgebroken taak blijft voor altijd in `bezig/` hangen waardoor een wachtende indiener oneindig blijft wachten.  
Techniek voor Claude: `brug.py:357-372,429,594-606` en `debat.py:276-280` - vang `SIGTERM`/`SIGHUP` op in `brug.py` en `overleg.py`, stop het actieve kindproces in `debat._draai` via `stop_proces`, en markeer bij het nemen van het luisterslot verweesde taken in `bezig/` als afgebroken.

2. **Wachtende of nieuwe indiener faalt tijdens de 5 seconden overdracht tussen twee luisteraars:**
Eens met Codex: de oude luisteraar wist `hartslag.json` direct bij het stoppen, terwijl de reserve-sidecar pas elke 5 seconden het slot probeert over te nemen. Wie in dat gat een overleg start of met `--wacht` wacht, krijgt ten onrechte een foutmelding dat de brug niet draait.  
Techniek voor Claude: `brug.py:291,331-333,562,602-606` - laat `--wacht` en indiening een korte overdracht overbruggen en laat `hartslag.json` staan of direct door de reserve overschrijven.

3. **Een enkele hapering bij de verbindingstoets blokkeert direct het oppakken van taken:**
Het ontwerp wil pas na drie mislukte metingen stoppen, maar na een enkele mislukte meting zet `meet()` `laatste_slecht` op waar en slaat de hoofdlus zowel een nieuwe meting als het claimen over (`--eenmalig` stopt dan direct zonder de wachtrij te verwerken). Daarnaast wacht `installeer_sidecar.sh` onnodig 60 seconden als er al een terminal-luisteraar draait.  
Techniek voor Claude: `brug.py:503-508,578-585` en `installeer_sidecar.sh:96-102` - hertoets bij een wachtende taak zolang `annuleer` niet gezet is, strip waarden in `geheimen_weg` (`brug.py:61-65`), en stop de wachtlus in `installeer_sidecar.sh` zodra `HUIDIGE_BRON="terminal"` is.

Overige punten zijn in orde: geen geheimen in hartslag/logs, `sidecar.json` klopt, en `DoorsturenViaBrug` bewijst doorsturen en exitcode 2 (graag aanvullen met tests voor `SIGTERM`, kindprocesgroepen en overdracht).

## Gezamenlijke Eindconclusie — CONTROLE (Codex) (gpt-6-sol · ultra, 141.2s)

**NO-GO. Codex en Gemini stemmen tegen livegang; ook als Claude GO stemt, is dat een 2-1 meerderheid. De maker kan de fouten herstellen zonder keuze van Mehdi.**

### Voor Mehdi

1. Het luisterslot houdt twee bruggen uit elkaar. Als de sidecar tijdens een overleg stopt, kunnen onderliggende AI-processen toch doorgaan terwijl de nieuwe brug alweer werk oppakt. De afgebroken opdracht kan bovendien blijven hangen. De stop moet eerst alle betrokken processen afronden of beëindigen en de opdracht een duidelijke eindstatus geven.

2. Bij overname kan de hartslag maximaal vijf seconden ontbreken. Een wachtende indiener krijgt dan een fout, terwijl zijn opdracht later alsnog kan draaien. De indiener moet die overdracht afwachten en een al aangenomen opdracht blijven volgen.

3. Als Antigravity spaties rond een adres of toegangscode meegeeft, schermt de brug de gebruikte waarde niet in alle uitvoer af. Dat moet worden hersteld voordat een log die waarde kan bewaren.

### Voor Claude en Shaniel

1. **Hoog, 2-1 in het voor livegang gunstigste geval.** [brug.py:389](/Users/mehdichegini/dev/_codex-brug-autostart/brug.py:389), [brug.py:594](/Users/mehdichegini/dev/_codex-brug-autostart/brug.py:594), [debat.py:276](/Users/mehdichegini/dev/_codex-brug-autostart/debat.py:276): vang `SIGTERM` en `SIGHUP` af, stop en wacht op afzonderlijke kindprocesgroepen vóór het slot vrijkomt; geef verweesde taken in `bezig/` bij overname een eindstatus. Test een echt kind in een eigen procesgroep.

2. **Hoog, 2-1 in het voor livegang gunstigste geval.** [brug.py:331](/Users/mehdichegini/dev/_codex-brug-autostart/brug.py:331), [brug.py:562](/Users/mehdichegini/dev/_codex-brug-autostart/brug.py:562), [overleg.sh:74](/Users/mehdichegini/dev/_codex-brug-autostart/overleg.sh:74): laat de voorcontrole en `--wacht` de overdracht overbruggen. Meld een aangenomen taak pas als mislukt wanneer vaststaat dat zij niet alsnog draait. Test een wachtende indiener tijdens overname.

3. **Hoog, 2-1 in het voor livegang gunstigste geval.** [brug.py:60](/Users/mehdichegini/dev/_codex-brug-autostart/brug.py:60), [brug.py:476](/Users/mehdichegini/dev/_codex-brug-autostart/brug.py:476): scherm zowel ruwe als `strip()`-waarden af; test adres en token met omringende spaties.

Het [sidecar-manifest](/Users/mehdichegini/dev/_codex-brug-autostart/installeer_sidecar.sh:51) heeft de gevraagde opties en `restart_policy: always`. [DoorsturenViaBrug](/Users/mehdichegini/dev/_codex-brug-autostart/test_overleg.py:479) bewijst doorsturen en exitcode 2 zonder levende brug, met een nepbrug; de drie situaties hierboven worden daarmee niet bewezen. Eén slechte meting geeft volgens het ontwerp tijdelijk uitstel, geen exitcode 3.

Gedaan: broncode en afspraken alleen gelezen.  
Nagekeken: slot, stoppen, overdracht, geheimen, sidecar en tests.  
Open: drie fixes, gerichte tests en een nieuwe livegangcontrole.
