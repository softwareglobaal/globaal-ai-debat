# Opdracht O9 - brug start vanzelf, ruimt verouderde luisteraars op, en doorsturen is getest (Codex maakt, Claude controleert)

Repo-worktree `~/dev/_codex-brug-autostart`, tak `codex/brug-autostart`, gebaseerd op origin/main 10b5a44.
Lees eerst `CLAUDE.md` en `README.md` van de repo en volg die. Niet committen of pushen: Claude doet dat.
Schrijf alleen in deze worktree. Raak niets aan in `~/.gemini`, `~/.overleg-brug`, `~/Library` of de hoofdrepo
`~/dev/globaal-ai-debat`. Lees nooit omgevingsvariabelen, argumenten of geheugen van andere processen (geen `ps eww`,
geen `/proc`, geen `lsof`) en schrijf nooit een adres of token weg. Alleen standaardbibliotheek, geen nieuwe pakketten.

## Waarom

De overleg-brug (`brug.py luister`, gestart via `brug.sh`) moet in een proces van Antigravity draaien, want alleen
daar staan `ANTIGRAVITY_LS_ADDRESS` en `ANTIGRAVITY_CSRF_TOKEN`. Nu start iemand hem met de hand. Na een herstart
van de Mac of van Antigravity is hij weg, en een achtergebleven luisteraar heeft dan een adres en token die niet
meer kloppen. Claude heeft gemeten (17-10-2026) hoe Antigravity 2.24 dat zelf oplost:

- Antigravity 2.24 is geen VS Code-afgeleide meer: er is geen extensie-host en `app.asar` bevat geen `tasks.json`,
  `runOptions` of `folderOpen`. Een taak in `.vscode/tasks.json` wordt dus nooit uitgevoerd.
- Wel heeft het **sidecars**: achtergrondprogramma's die de Antigravity-server zelf start en bewaakt. Uit de
  handleiding die in `Antigravity.app/Contents/Resources/bin/language_server` zit:
  - plaats: `~/.gemini/config/sidecars/<sidecar-id>/sidecar.json` (een map per sidecar, mapnaam = id);
  - voorbeeld: `{"command": "python3", "args": ["sidecar.py"], "restart_policy": "always", "description": "..."}`;
  - de opdracht draait met als werkmap de map van de sidecar;
  - "The server is constantly watching the directory. If a sidecar is deleted, the server will kill the command.
    If a sidecar is added or edited, the server will start or restart the command."; uitzetten in de app stopt hem;
  - statussen STARTING, RUNNING, STOPPED, ERRORED, BACKOFF; de server draait met `--enable_sidecars`;
  - de server zet in de omgeving van een sidecar o.a. `ANTIGRAVITY_SIDECAR_WEB_PORT` en
    `ANTIGRAVITY_EXECUTABLE_DATA_DIR`; de meegeleverde `~/.gemini/config/node_modules/sidecar_sdk/index.mjs` leest
    `ANTIGRAVITY_LS_ADDRESS` en `ANTIGRAVITY_CSRF_TOKEN` uit `process.env` van de sidecar. Een sidecar erft dus de
    Antigravity-toegang, telkens vers van de server die draait.
  - Een nieuwe sidecar moet de gebruiker mogelijk zelf aanzetten in Antigravity, scherm Automations
    (`sidecar://dashboard`). Dat is Mehdi's ene klik; nooit zelf `config.json` aanpassen om hem aan te zetten.
- Claude mag van zijn beveiligingslaag zelf geen sidecar neerzetten. Daarom komt er een installatiescript dat Mehdi
  één keer draait.
- Een zuinige oproep met token: `POST http://<adres>/exa.language_server_pb.LanguageServerService/Heartbeat`, body
  `{}`, kop `x-codeium-csrf-token`. Welke HTTP-code een verkeerd token geeft is NIET gemeten; ontwerp daarom
  zelfijkend (zie B3).

## Wat te bouwen

### A. Regressietest voor het automatisch doorsturen (test_overleg.py of test_brug.py)

Commit 10b5a44 laat `overleg.sh` en `overleg.py` (`draai_overleg`) zelf indienen via `brug.py indienen --wacht` als
de Antigravity-omgeving ontbreekt en `brug.brug_leeft()` waar is; ook `overleg.sh --zelftest` loopt zo. Er is geen
test voor. Schrijf tests met een **nep-luisteraar** (stub) in het testproces of als kindproces: schrijft
`hartslag.json` in `OVERLEG_BRUG_MAP` (pid van een levend proces, verse `laatste_tik`, ververst zolang de test
loopt), neemt opdrachten uit `wachtrij/`, schrijft een vast rapport (bv. `RAPPORT VIA BRUG`) naar het gevraagde
rapportpad en zet een eindstatus in `klaar/` zoals `brug.verwerk` dat doet. Geen netwerk, geen abonnement, geen
echte Codex of Gemini. De omgeving van het geteste proces bevat GEEN `ANTIGRAVITY_LS_ADDRESS`,
`ANTIGRAVITY_CSRF_TOKEN`, `GEMINI_AGENTAPI` of `GEMINI_BRAIN_DIR`; `HOME` en `OVERLEG_BRUG_MAP` wijzen naar een
tijdelijke map, `AI_DEBAT` naar deze repo, `CODEX_SH_PY` naar `sys.executable`, `CODEX_SH_RUNS` naar een tijdelijke
map (nooit naar `runs/` van de repo).

Bewijs met aparte tests:
1. `overleg.sh -C <map> -o <rapport> -t <titel> -T 30 < opdracht` met levende nep-brug: exit 0, stdout bevat het
   rapport, en de nep-brug kreeg precies één opdracht met de juiste werkmap, titel, opdrachttekst en opties
   (minstens `b`, `g`, `T`).
2. Hetzelfde via `overleg.py` (`overleg.main([...])` of `draai_overleg`): returncode 0 en het rapport op stdout.
3. Zonder levende brug (geen hartslag, en apart: een verlopen hartslag): `overleg.sh` geeft exitcode 2 en de
   bekende melding `Gemini-toegang ontbreekt` op stderr, en er komt niets in de wachtrij; `overleg.py` idem
   (returncode 2, zelfde melding).
4. `overleg.sh --zelftest` met levende nep-brug: exit 0 en `zelftest geslaagd`. Dat vraagt ook dat
   `--verwerking` slaagt (zie `codex.sh --verwerking`: rondebestand `<rapport>.ronde` en een ronde in
   `CODEX_SH_RUNS`); laat de nep-brug dat netjes aanmaken met `ronde.py`. Lukt dit echt niet zonder een echte
   Codex, leg dan uit waarom en test minstens het overleg-deel van de zelftest.

POSIX-only waar nodig (`skipUnless os.name == "posix"`), op Windows netjes overslaan.

### B. Luisteraar start vanzelf en ruimt zichzelf op als hij veroudert (brug.py, brug.sh)

1. **`luister --wacht-op-slot`**: is het slot bezet, dan niet stoppen maar wachten als reserve: elke 5 s opnieuw
   proberen (`fcntl.flock` LOCK_NB), één keer melden `Er draait al een luisteraar; deze wacht als reserve`. Een
   reserve schrijft geen hartslag en claimt niets. Zonder de optie blijft het gedrag zoals nu (exit 2, `Er draait al
   een luisteraar`). Er mogen nooit twee luisteraars tegelijk opdrachten verwerken: hergebruik het bestaande slot
   `_neem_slot`, bouw geen tweede.
2. **`luister --ouder-bewaken`**: onthoud `os.getppid()` bij de start. Verandert die (ouder weg, wees-proces), dan
   netjes stoppen (hartslag weg, slot los) met exitcode 3 en de melding `Antigravity is gestopt; luisteraar stopt`.
   Ook tijdens het reservewachten.
3. **Toegangscontrole** (altijd aan in `luister`): functie `toegang(adres, token, timeout=3) -> str` met uitkomst:
   - `"weg"`: geen verbinding (geweigerd, time-out, onbereikbaar, ongeldig adres);
   - `"geweigerd"`: HTTP 401 of 403;
   - `"ok"`: elk ander antwoord (2xx, 400, 404, 500 ...): de server op dat adres leeft en weigerde het token niet.
   Gebruik de Heartbeat-oproep hierboven, met `urllib` en een korte time-out. Zelfijkend:
   - bij de start één meting. `"weg"` = verouderd: meteen stoppen met exitcode 3. `"geweigerd"` bij de start
     betekent dat deze oproep het token niet kan toetsen: dan telt later alleen `"weg"`, en meld dat één keer.
   - daarna elke `--toegang-interval` seconden (standaard 30, toegestaan 0.2 tot 600) en altijd vlak voor het
     claimen van een opdracht als de laatste geslaagde meting ouder is dan 10 s.
   - 3 slechte metingen na elkaar = verouderd: netjes stoppen, exitcode 3, melding
     `Antigravity-gegevens van deze luisteraar kloppen niet meer (Antigravity herstart?); luisteraar stopt`.
   - zolang de laatste meting slecht is, claimt hij geen opdrachten.
   - nooit adres, token of serverantwoord in een melding, log, status of hartslag; alleen het woord van de uitkomst.
4. **Exitcodes**: `luister` geeft 0 bij Ctrl+C, 3 bij verouderd of ouder weg, 2 bij een fout zoals nu. `main()` geeft
   ze door. Constante `VEROUDERD = 3`.
5. **Hartslag**: veld `"bron"`: `"sidecar"` als `ANTIGRAVITY_SIDECAR_WEB_PORT` of
   `ANTIGRAVITY_EXECUTABLE_DATA_DIR` in de omgeving staat, anders `"terminal"`. `VERSIE = 2`. `brug.py status` toont
   de bron. `brug_leeft()` blijft werken met hartslagen van versie 1 en 2.
6. **`geen_brug()`**: noem beide wegen kort: eenmalig `~/dev/globaal-ai-debat/installeer_sidecar.sh` (en de sidecar
   `overleg-brug` aanzetten in Antigravity, Automations), anders `brug.sh` in de Terminal van Antigravity.
7. **`brug.sh`**: geeft opties door zoals nu; de commentaarregel bovenaan vertelt dat de sidecar hem normaal start.

### C. Installatiescript `installeer_sidecar.sh` (nieuw, bash, macOS en Linux)

- `installeer_sidecar.sh`: schrijft `${ANTIGRAVITY_CONFIG_DIR:-$HOME/.gemini/config}/sidecars/overleg-brug/sidecar.json`
  met: `"command": "/bin/bash"`, `"args": ["<absoluut pad naar deze repo>/brug.sh", "--ouder-bewaken",
  "--wacht-op-slot"]`, `"restart_policy": "always"`, en een korte Nederlandse `"description"`. JSON maken met Python
  `json.dumps` (geen zelfgebouwde aanhalingstekens). Map 0700, bestand 0600, atomisch (tijdelijk bestand + `mv`).
  Idempotent: een tweede keer draaien geeft hetzelfde bestand.
- Weigert (exit 2, duidelijke melding) als `.venv/bin/python` ontbreekt of als de configmap van Antigravity niet
  bestaat (Antigravity 2.x niet geinstalleerd). Maakt de configmap niet zelf aan; wel `sidecars/overleg-brug/`.
- Daarna: wacht tot 60 s (`--niet-wachten` slaat over) op een levende hartslag met bron `sidecar` en meldt:
  `Sidecar draait`, of `Er draait nog een luisteraar uit een terminal; de sidecar wacht als reserve en neemt over zodra
  die stopt`, of `Zet 'overleg-brug' aan in Antigravity: Automations`. In alle drie de gevallen exit 0.
- `--toon`: druk de JSON af die hij zou schrijven, verander niets. `--verwijder`: haalt alleen
  `sidecars/overleg-brug/` weg (en niets anders). `--help`.

### D. Tests voor B en C (test_brug.py)

De bestaande luisteraartests gebruiken een nepadres zonder poort; met de toegangscontrole stopt die luisteraar nu
meteen. Geef de tests een **nep-Antigravity-server**: een `http.server.ThreadingHTTPServer` op `127.0.0.1:0` in het
testproces die op elk pad antwoordt met een instelbare code (200, 403) en die je kunt stilleggen. Zet
`ANTIGRAVITY_LS_ADDRESS` op `127.0.0.1:<poort>` en houd de bestaande geheimen-test (adres en token komen nergens
terug) werkend. Nieuwe tests, met `--toegang-interval` klein:
1. reserve: tweede luisteraar met `--wacht-op-slot` blijft draaien zonder hartslag te schrijven of te claimen; na het
   stoppen van de eerste neemt hij over (hartslag-pid = tweede) en verwerkt een opdracht.
2. zonder `--wacht-op-slot` blijft de tweede weigeren met exit 2.
3. server weg na de start: luisteraar stopt met exit 3 binnen enkele seconden, hartslag weg, slot vrij (een nieuwe
   luisteraar kan meteen starten).
4. server gaat na de start op 403: exit 3. Server geeft al bij de start 403: luisteraar blijft draaien zolang de
   server bereikbaar is, en stopt pas met exit 3 als de server weg is.
5. adres onbereikbaar bij de start: meteen exit 3.
6. tijdens slechte metingen wordt een opdracht in de wachtrij niet geclaimd.
7. `--ouder-bewaken`: start de luisteraar via een tussenproces dat daarna stopt; de luisteraar stopt met exit 3.
8. hartslag heeft `bron` `terminal`, en `sidecar` als `ANTIGRAVITY_SIDECAR_WEB_PORT` gezet is; `status` toont het.
9. installatiescript met `ANTIGRAVITY_CONFIG_DIR` in een tijdelijke map: `--toon` geeft geldige JSON met het
   absolute pad naar `brug.sh`, de twee opties en `restart_policy` `always`; installeren met `--niet-wachten` schrijft
   het bestand met rechten 0600 en map 0700; tweede keer identiek; `--verwijder` haalt alleen die map weg; zonder
   configmap exit 2.

Bestaande tests mogen niet zwakker worden. Tests snel houden (geen vaste lange `sleep`, alles onder een paar seconden
per test).

### E. Documentatie

- `CLAUDE.md`: rij in de bestandentabel voor `installeer_sidecar.sh`; regel bij gebruik en onderhoud: de brug start als
  sidecar van Antigravity, een luisteraar stopt zelf bij verouderde gegevens (exit 3), nooit `config.json` van
  Antigravity aanpassen om een sidecar aan te zetten, `.vscode/tasks.json` werkt niet in Antigravity 2.x; rij bij de
  valkuilen voor een verouderde luisteraar na een herstart van Antigravity.
- `README.md`: korte sectie over de brug als sidecar en wat Mehdi één keer doet (script draaien, sidecar aanzetten).

## Klaar betekent

- Draai vanuit de worktree: `/Users/mehdichegini/dev/globaal-ai-debat/.venv/bin/python -m unittest test_grendels
  test_ronde test_codex_sh test_meting test_overleg test_brug -v`. Alles groen. Blokkeert je sandbox het openen van
  een poort op 127.0.0.1 of iets anders, zeg dan precies welke test en welke fout; Claude draait ze dan zelf.
- `bash -n` op alle gewijzigde `.sh`-bestanden.
- Antwoord in het Nederlands, kort: wat je veranderde per bestand, welke tests erbij kwamen, de testuitslag (aantal,
  OK of niet), en wat je niet kon doen of bewust anders deed, met reden.
