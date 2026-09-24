# ai-debat: instructies voor Claude

Dit bestand is voor de Claude Code-sessie die deze app installeert of onderhoudt. Wat de
app doet staat in [README.md](README.md). Lees dat eerst.

## Wie doet wat

- **Jij (Claude)** voert de installatie uit en controleert na elke stap zelf of hij
  gelukt is. Meld pas "klaar" als alle controles onderaan groen zijn.
- **De gebruiker** doet de twee logins zelf in de browser. Vraag nooit om een wachtwoord,
  token of code en typ er nooit een in. Geef het commando, wacht tot de gebruiker zegt dat
  het gelukt is, en controleer het dan zelf.

## Installatie

Werk van boven naar beneden. Gaat een controle mis, los dat eerst op; ga niet door.

### 1. Voorwaarden

```
python --version      # 3.10 of hoger (op macOS/Linux: python3)
node --version        # nodig voor npm
git --version
claude --version      # Claude Code zelf
```

Ontbreekt er iets, installeer het met de gebruikelijke weg voor het besturingssysteem en
vraag de gebruiker om toestemming voor je iets systeembreed installeert.

Claude Code ouder dan 2.1.251 kan het model `fable` niet gebruiken. Dat is geen blokkade,
de andere modellen werken wel; `controleer_modellen.py` sluit `fable` dan vanzelf uit.
Werk Claude Code niet bij vanuit de sessie die je zelf draagt.

### 2. Codex CLI

```
npm install -g @openai/codex
codex --version
```

### 3. Logins (de gebruiker doet dit)

Codex:

```
codex login
```

Dit opent de browser; de gebruiker logt in met zijn ChatGPT-account. Elk ChatGPT-plan
werkt, ook het gratis. Controle, die moet je zelf doen:

```
codex login status          # verwacht: "Logged in using ChatGPT"
```

Claude: de CLI die jij draait is meestal al ingelogd. Controleer het met de rooktest in
stap 5. Geeft die "OAuth session expired" of "Failed to authenticate", laat de gebruiker
dan in een eigen terminal `claude` starten en `/login` doen.

### 4. Python-omgeving

Windows:

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

macOS en Linux:

```
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
chmod +x start.sh
```

Gebruik daarna overal de python uit `.venv`. De startscripts doen dat vanzelf.

### 5. Rooktest per kant

```
python test_kant.py claude
python test_kant.py codex
```

Elk moet een korte Nederlandse tekst over koffie teruggeven. Een foutmelding over
authenticatie betekent: terug naar stap 3.

### 6. Modellen vaststellen

```
python controleer_modellen.py
```

Dit probeert per model een vraag van een paar woorden en schrijft `modellen.json` met
alleen de modellen die op deze machine werken. Het weigert te schrijven als een kant
helemaal niets heeft; dat is bijna altijd een verlopen login. Laat de uitvoer aan de
gebruiker zien: welke modellen werken en welke geweigerd zijn.

### 7. Starten

Windows: `start.cmd`. macOS en Linux: `./start.sh`.

De browser opent op http://127.0.0.1:8099. Controleer zelf:

```
curl -s http://127.0.0.1:8099/api/modellen      # "gecontroleerd_op" moet een datum zijn
curl -s http://127.0.0.1:8099/api/onderwerpen   # bevat voorbeeld-consolidatie.json
```

**Start de server nooit via een preview- of launch-functie van een IDE of van Claude
Code zelf.** Daar blijven de `claude`-subprocessen stil hangen op het lezen van hun
login: CPU vlak, geen fout, geen voortgang. Altijd via een gewone terminal of het
startscript.

### 8. Eerste debat

Kies in de interface `voorbeeld-consolidatie`, zet Beurten op 4 en start. Na ongeveer
twee minuten moeten er vier beurten staan, afwisselend Claude en ChatGPT. Pas dan is de
installatie klaar.

## Klaar betekent

- [ ] `codex login status` zegt ingelogd met ChatGPT
- [ ] beide rooktests geven tekst terug
- [ ] `modellen.json` bestaat en heeft minstens een model per kant
- [ ] de pagina laadt op http://127.0.0.1:8099
- [ ] een debat van 4 beurten is volledig doorgelopen

Meld aan de gebruiker welke modellen werken, en waar de app staat.

## Regels bij gebruik en onderhoud

- **Geen tools in debatmodus.** Beide kanten draaien zonder tools: Claude met
  `--safe-mode --tools ""`, Codex met `--sandbox read-only`. Een debatdeelnemer met tools
  is een prompt-injectiekanaal, want hij leest de tekst van de ander.
- **Bash blijft standaard uit in opdrachtmodus.** De uitvoerder krijgt de reviewtekst
  binnen; met Bash aan kan een zin daarin een commando worden. Het vinkje in de interface
  is een bewuste keuze van de gebruiker per opdracht, niet iets om standaard aan te zetten.
- **Opdrachtmodus werkt alleen in een git-worktree.** Nooit in de werkende map van de
  gebruiker, nooit pushen, nooit deployen. De worktree blijft staan; de gebruiker beslist.
- **Wat naar OpenAI gaat.** Alles in `context` en `briefing` gaat mee naar de
  ChatGPT-kant. Geen hostnamen, IP-adressen, e-mailadressen, sleutels of persoonsgegevens.
  De briefing-scan waarschuwt, maar haalt niets weg.
- **Draai dit lokaal.** De logins staan op deze machine. Niet op een server zetten
  zonder dat de gebruiker daar bewust voor kiest; dan moeten de logins daar opnieuw en
  deelt die server de abonnementen.

## Bekende valkuilen

Dit zijn dingen die al een keer tijd hebben gekost. Kijk hier eerst.

| verschijnsel | oorzaak | oplossing |
| --- | --- | --- |
| `FileNotFoundError` bij het starten van codex op Windows | `codex` is een `.CMD`-shim; Python 3.13 start die niet op naam alleen | `debat.vind()` zoekt het volledige pad op met `shutil.which`; altijd die gebruiken |
| beurt blijft eindeloos "aan het schrijven" | server gestart via een preview-launcher | stoppen en via `start.cmd` of `start.sh` starten |
| "OAuth session expired" | Claude-login verlopen | gebruiker doet `/login` in een eigen `claude`-sessie |
| model staat in de lijst maar geeft een fout | lijst niet gecontroleerd op deze machine | `python controleer_modellen.py` |
| Bewaren in het onderwerpvenster doet niets | het `close`-event van `<dialog>` vuurt niet betrouwbaar | acties hangen aan de klik op de knop; niet terug naar het close-event |
| element met `hidden` blijft zichtbaar | een klasse met `display: flex` wint van `hidden` | `[hidden] { display: none !important; }` staat in de CSS; laten staan |
| accenten worden vreemde tekens in de console | Windows-console is geen UTF-8 | `debat.py` zet stdout op UTF-8; bestanden altijd met `encoding="utf-8"` |

## Bestanden

| bestand | doel |
| --- | --- |
| `web.py` | Flask-server op 127.0.0.1:8099, draait debat en opdracht in een thread |
| `pagina.html` | de hele interface, zonder framework |
| `debat.py` | aanroepen van beide CLI's, prompts, stoppen, en een opdrachtregelversie |
| `opdracht.py` | worktree, diff, uitvoerder- en reviewerprompts |
| `verkenner.py` | briefing van een projectmap maken en scannen op gevoelige gegevens |
| `controleer_modellen.py` | vaststellen welke modellen op deze machine werken |
| `test_kant.py` | rooktest per kant |
| `modellen.standaard.json` | veilige lijst tot `controleer_modellen.py` heeft gedraaid |
| `onderwerpen/voorbeeld-*.json` | voorbeeldonderwerpen; eigen onderwerpen blijven buiten git |
