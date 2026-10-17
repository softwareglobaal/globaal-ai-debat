# Driehoeksoverleg (Codex, Gemini & Claude): O9b brug autostart: tweede toets 2-op-3
Ronde in dashboard: `20261017-163845-codex` (http://127.0.0.1:8099)
Modellen en denkstand:
- Claude: `claude-opus-5-5` (denkstand: `xhigh`)
- Codex: `gpt-6-sol` (denkstand: `ultra`)
- Gemini (Antigravity): `Gemini 4 Argon (High)` (`gemini-4-argon`, denkstand: `high`)

## OVERLEG (Codex) (gpt-6-sol · ultra, 276.0s)

**NO-GO van Codex. Mijn stem is 1 tegen; Claude en Gemini moeten nog stemmen over deze herstelronde.**

De eerdere punten 1 tot en met 4 zijn in de code aangepakt. De gemelde 150 geslaagde tests dekken stoppen, reserveovername, geheimen met spaties en herstel na één slechte meting. Ze bewijzen de volgende grensgevallen niet:

1. **De automatische overname kan een net begonnen overleg stoppen.** De installateur ziet tweemaal een lege map `bezig/`, maar de oude luisteraar kan direct daarna een taak aannemen, vóór hij `SIGINT` krijgt. Mehdi ziet dan een afgebroken overleg terwijl de brug gezond was.  
   Techniek voor Claude: `installeer_sidecar.sh:135-149` - pauzeer de oude luisteraar, bevestig dat hij stilstaat en `bezig/` leeg is, en stuur pas dan het stopsignaal. Test een claim precies tussen controle en signaal.

2. **Een afgeronde taak kan na een crash als mislukt verschijnen.** De eindstatus wordt geschreven vóór het taakbestand verhuist. Crasht de luisteraar daartussen, dan overschrijft de opvolger die eindstatus met exitcode 3. Zonder opvolger stopt `--wacht` na 120 seconden terwijl de taak in `bezig/` blijft.  
   Techniek voor Claude: `brug.py:381-384,468-474,543-546` - behoud een al geschreven geldige eindstatus; laat de wachtende indiener een verweesde taak afsluiten zodra hij het vrije luisterslot heeft.

3. **Een foutief adres kan het token naar buiten sturen.** De nieuwe toegangstoets accepteert ook een niet-lokaal adres; de echte Gemini-aanroep doet dat eveneens.  
   Techniek voor Claude: `brug.py:297-318`, `debat.py:356-369` - sta vóór beide verzoeken uitsluitend gecontroleerde loopback-adressen toe.

4. **‘Nu stoppen’ heeft een kleine maar ernstige procesrace.** Na het uitlezen van een proces kan dat al beëindigd zijn; `stop_proces` stuurt toch een signaal naar zijn oude groepsnummer, dat inmiddels hergebruikt kan zijn.  
   Techniek voor Claude: `web.py:439-445`, `debat.py:155-165` - koppel stoppen en opruimen aan dezelfde bewaakte proceslevensduur; signaleer geen vrijgekomen groepsnummer.

Gedaan: alleen code en tests gelezen.  
Nagekeken: vijf herstelpunten en de webapp-stoproute.  
Open: vier blokkades herstellen en gericht testen.

## OVERLEG (Gemini) (Gemini 4 Argon (High), 234.3s)

**NO-GO (voorlopig 2-0 met Codex, Claude stemt hierna): de vijf eerdere fouten zijn verholpen en getest, maar er zitten nog vier randgevallen in die eerst hersteld moeten worden.**

Ik ben het eens met de vier blokkades van Codex en vul op punt 1 en 3 twee blinde vlekken in de code aan:

1. **Een stopsignaal of sidecar-overname kan een taak op een onbewaakt moment treffen.**  
   Codex ziet terecht dat de oude luisteraar net tussen de controle en het stopsignaal van het installatiescript een taak kan aannemen. Daar komt in `brug.py` nog iets bij: een stopsignaal gooit nu direct een onderbreking, ook als de luisteraar net een opdracht verplaatst of net klaar is met het overleg en de eindstatus wegschrijft. Mehdi merkt dan dat een net gestart of zelfs al afgerond overleg alsnog kapotgaat of in `bezig/` blijft hangen.  
   Techniek voor Claude: `brug.py:400-410, 497-548, 606-614` en `installeer_sidecar.sh:102-106, 135-149` - laat `stop_signaal` een stop-event zetten in plaats van een rauwe `KeyboardInterrupt` midden in bestandswissels te gooien (en behoud de loguitvoer van `_stop_procesgroep` in `_draai`); controleer in `installeer_sidecar.sh` dat zowel `wachtrij/` als `bezig/` leeg zijn met `kill -STOP`, hercontrole en pas daarna `kill -INT` + `kill -CONT`.

2. **Een afgeronde taak kan na een crash als mislukt tellen of bij de indiener blijven hangen.**  
   Crasht de luisteraar nadat de eindstatus is geschreven maar voor het taakbestand verhuist, dan overschrijft de volgende luisteraar het geslaagde resultaat met exitcode 3. Is er geen volgende luisteraar, dan wacht de indiener 120 seconden zonder dat de taak in `bezig/` wordt afgesloten.  
   Techniek voor Claude: `brug.py:381-385, 448-474` - als `bezig/<id>.status.json` al toestand `klaar` of `fout` heeft, verplaats die bestanden in `herstel_verweesde_taken` naar die doelmap in plaats van te overschrijven met exitcode 3 (en verwijder een eventuele wees `wachtrij/<id>.status.json`); laat `dien_in --wacht` zonder levende brug onder `_neem_slot` zelf `herstel_verweesde_taken` aanroepen.

3. **De adrescontrole en Gemini-aanroep schermen niet-lokale adressen en proxy's nog niet volledig af.**  
   Codex wijst er terecht op dat een niet-lokaal adres nog wordt doorgelaten. Aanvullend: `brug.toegang` negeert systeemproxy's en omleidingen netjes, maar `debat._antigravity_rpc` gebruikt nog een kale `urlopen`, waardoor een ingestelde `HTTP_PROXY` het token alsnog naar buiten kan sturen.  
   Techniek voor Claude: `brug.py:302-306` en `debat.py:356-370` - sta in beide functies uitsluitend loopback-hosts (`127.0.0.1`, `localhost`, `::1`) toe en gebruik ook in `debat._antigravity_rpc` `ProxyHandler({})` plus `GeenOmleiding`.

4. **‘Nu stoppen’ in de webapp kan na afloop van een beurt een vrijgekomen procesgroep raken.**  
   Klikt iemand op ‘Nu stoppen’ precies als een beurt vanzelf klaar is, dan kan de app buiten het slot om een signaal sturen naar een al opgeruimd groepsnummer.  
   Techniek voor Claude: `web.py:94-101, 439-446` en `debat.py:155-173` - voer `stop_proces(HUIDIG["proc"])` in `web.py` binnen `with LOCK:` uit en stuur geen `killpg` op een proces dat al buiten `_draai` met `wait()`/`communicate()` is afgerond.

## Gezamenlijke Eindconclusie — CONTROLE (Codex) (gpt-6-sol · ultra, 148.2s)

**NO-GO: Codex en Gemini vormen de meerderheid tegen een push naar main.** Claude’s stem over deze herstelronde ontbreekt in de aangeleverde stand: de eindverhouding wordt 2-1 als Claude GO stemt, of 3-0 als Claude NO-GO stemt. Mehdi hoeft hierover niet te kiezen.

### Voor Mehdi

De vijf eerdere fouten zijn gericht aangepakt. De gemelde 150 geslaagde tests en drie herhalingen bevestigen de geteste situaties, maar dekken vier kritieke momenten niet af:

1. Bij de automatische overname kan de oude luisteraar nét een overleg beginnen voordat hij wordt gestopt. De overdracht moet eerst veilig worden stilgezet en opnieuw gecontroleerd.
2. Na een crash kan een al afgerond overleg alsnog als mislukt verschijnen, of zonder eindstatus blijven hangen. Het herstel moet de bestaande uitkomst bewaren en een wachtende indiener moet een verweesde taak kunnen afsluiten.
3. Een verkeerd ingesteld adres kan de toegangscode buiten de Mac brengen. Beide verbindingsroutes moeten uitsluitend een lokaal adres gebruiken, zonder proxy of omleiding.
4. ‘Nu stoppen’ kan in een zeldzame race een inmiddels vrijgekomen procesnummer raken. Het lopende overleg moet zijn eigen stopverzoek afhandelen.

Ik vond in de gecontroleerde claimroute geen afzonderlijke aanwijzing voor dubbele verwerking.

### Voor Claude en Shaniel

Voor elk punt geldt: **hoog, Codex en Gemini akkoord (2 van 3); exacte eindverhouding volgt Claude’s stem**.

1. [installeer_sidecar.sh:135](/Users/mehdichegini/dev/_codex-brug-autostart/installeer_sidecar.sh:135), [brug.py:606](/Users/mehdichegini/dev/_codex-brug-autostart/brug.py:606): pauzeer de oude luisteraar, verifieer dezelfde PID en lege `wachtrij/` én `bezig/`, stuur dan pas het stopsignaal en hervat gegarandeerd. Vervang de directe `KeyboardInterrupt` door een stop-event zodat bestandsverplaatsingen worden afgerond.
2. [brug.py:383](/Users/mehdichegini/dev/_codex-brug-autostart/brug.py:383), [brug.py:468](/Users/mehdichegini/dev/_codex-brug-autostart/brug.py:468), [brug.py:543](/Users/mehdichegini/dev/_codex-brug-autostart/brug.py:543): behoud een geldige eindstatus bij herstel; laat `--wacht` een verweesde taak herstellen zodra het luisterslot vrij is.
3. [brug.py:302](/Users/mehdichegini/dev/_codex-brug-autostart/brug.py:302), [debat.py:369](/Users/mehdichegini/dev/_codex-brug-autostart/debat.py:369): valideer in beide routes een loopback-adres en schakel proxy’s en HTTP-omleidingen uit.
4. [web.py:445](/Users/mehdichegini/dev/_codex-brug-autostart/web.py:445), [debat.py:165](/Users/mehdichegini/dev/_codex-brug-autostart/debat.py:165): laat `_draai` het stopverzoek verwerken vóór het ouderproces wordt opgeruimd. Alleen een slot rond `web.py` sluit deze race niet.

Gedaan: alleen gelezen.  
Nagekeken: broncode, testdekking en de gemelde testuitslagen.  
Open: vier fixes, gerichte racetests en onafhankelijke hercontrole vóór push.
