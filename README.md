# ai-debat

Laat Claude en ChatGPT met elkaar praten op de abonnementen, zonder API-keys.

- Claude-kant: `claude -p` via Claude Code, draait op het Claude-abonnement.
- ChatGPT-kant: `codex exec` via Codex CLI, draait op het ChatGPT-abonnement.
- De orkestrator wisselt de beurten af, schrijft alles weg en dwingt de limieten af.

Twee modi: **Opdracht** (Claude schrijft code in een git-worktree, de app draait jouw tests,
Claude herstelt tot ze groen zijn) en **Debat** (Claude en ChatGPT verdedigen een
tegengestelde positie, een rechter sluit af met een vonnis). Opdracht is de kern en staat
standaard aan. In de opdrachtmodus doet ChatGPT niet mee; zie hieronder waarom.

Elke run eindigt in velden, niet in een gesprek: een opdracht in `resultaat.json` (tests,
rondes, duur, waarom gestopt, jouw oordeel), een debat in `vonnis.json` (besluit, winnaar,
open punten, volgende stap).

## Installeren

Laat je eigen Claude Code het doen: open deze map in Claude Code en zeg "installeer dit".
De stappen, met een controle na elke stap, staan in [CLAUDE.md](CLAUDE.md). Die wordt
automatisch gelezen.

Nodig: Python 3.10+, Node.js (voor npm), git, een Claude-abonnement en een ChatGPT-account.
De twee logins doe je zelf in de browser; niemand anders hoeft je wachtwoord.

## Webinterface (de gewone manier)

Windows: dubbelklik op `start.cmd`. macOS: dubbelklik op `start.command`. Linux:
`./start.sh`. Of rechtstreeks:

```
python web.py
```

De browser opent op http://127.0.0.1:8099. Daar kies je het onderwerp, stel je de
beurten en modellen in, volg je het debat live en breng je als moderator berichten in.
Eerdere runs staan links en zijn met een klik terug te lezen.

De app luistert alleen op loopback. Start hem niet via een IDE-preview-launcher: de
`claude`-subprocessen blijven dan hangen op het lezen van hun login. Vanuit een gewone
terminal of via `start.cmd` werkt het wel.

## Draaien vanaf de opdrachtregel

```
python debat.py --beurten 12
python debat.py --onderwerp onderwerpen/voorbeeld-consolidatie.json --beurten 20 --max-woorden 300
python debat.py --droogloop            # alleen de prompts tonen, niets aanroepen
python test_kant.py claude             # rooktest per kant
python test_kant.py codex
```

Belangrijkste vlaggen:

| vlag | betekenis |
| --- | --- |
| `--beurten` | totaal aantal beurten, verdeeld over beide kanten |
| `--max-woorden` | lengtelimiet per beurt |
| `--claude-model` | bijvoorbeeld `sonnet` of `opus`; zie `modellen.json` voor wat hier werkt |
| `--codex-model` | leeg = standaardmodel van codex; zie `modellen.json` |
| `--start` | wie het debat opent |
| `--stop-bij-instemming` | stop zodra beide kanten achter elkaar `STANDPUNT: EENS` melden |
| `--geen-vonnis` | geen rechter na afloop |

## Resultaat

Per run komt er een map in `runs/<tijdstip>/`:

- `board.jsonl` - één regel per beurt met spreker, model, tijdstip, duur, tekst en standpunt
- `transcript.md` - leesbaar verslag, bij een debat met het vonnis onderaan
- `onderwerp.json` - kopie van het gebruikte onderwerp
- `vonnis.json` - debat: het vonnis van de rechter in velden
- `resultaat.json` - opdracht: de feiten van de run plus jouw oordeel
- `tests-start.txt`, `tests-ronde-<n>.txt` - opdracht: volledige testuitvoer per meting
- `injectie.txt` - zie hieronder

## Debat: standpunt en vonnis

Elke beurt eindigt met een vaste regel: `STANDPUNT: HANDHAAF`, `BIJGESTELD` of `EENS`. De
app haalt die regel uit de tekst en toont hem bij de beurt. Melden beide kanten achter
elkaar `EENS`, dan stopt het debat: verder praten levert dan niets meer op.

Na elk debat dat niet met Nu stoppen is afgebroken, leest een rechter (een aparte
Claude-aanroep zonder tools) het hele debat en geeft een vonnis in velden: besluit,
winnaar, doorslaggevend argument, waar ze het over eens werden, open punten en de
volgende stap. De rechter ziet de kanten alleen als A en B, niet als Claude en ChatGPT.
Lukt het lezen van zijn antwoord niet, dan staat er een zichtbare fout met de ruwe tekst.

## Rondes tussen Claude en Codex

Claude roept Codex ook buiten deze interface aan, met `codex.sh` (`codex exec`, standaard alleen
lezen en zonder MCP-servers). Elke aanroep wordt een run in `runs/<tijdstip>-codex/` en staat
links bij de eerdere runs met het label "Codex-ronde". Een ronde heeft deze beurten:

1. OPDRACHT (Claude aan Codex)
2. CONTROLE (Codex), of FOUT als Codex faalde of onderbroken werd
3. VERWERKING (Claude): per bevinding het oordeel, het herstel en de test

```
codex.sh -C <map> -o <rapport.md> -t "<titel>" < opdracht.md
codex.sh --verwerking <rapport.md> < verwerkt.md
codex.sh --zelftest
```

`ronde.py` schrijft de runs weg in hetzelfde formaat als een debat. Zo staat al het werk van
Claude en Codex samen op één plek.

Voor overleg met Codex én Gemini gebruik je `overleg.sh`. Buiten Antigravity stuurt het
automatisch via de draaiende brug door; anders gebruik je de **Terminal van Antigravity**
(`Terminal > New Terminal`). Het schrijft hun beurten en de gezamenlijke eindconclusie
in het dashboard en in het rapport:

```
overleg.sh -C <map> -o <rapport.md> [-t "<titel>"] [-b 2] [-m codex-model] [-e niveau] [-g pro|flash|flash_lite] [-T seconden] < opdracht.md
overleg.sh --verwerking <rapport.md> < verwerkt.md
```

`-b` bepaalt de diepte, `-m` het Codex-model, `-e` het redeneerniveau, `-g` het
Gemini-model en `-T` de timeout per beurt (standaard 1200 seconden). Met `--verwerking`
voegt Claude zijn slotbeurt aan dezelfde ronde toe.

### Overleg-brug

Eenmalig draait Antigravity zelf `~/dev/globaal-ai-debat/installeer_sidecar.sh` (Mehdi vraagt
het in gewone taal) en zet Mehdi zo nodig `overleg-brug` aan in Antigravity > Automations. Antigravity start en bewaakt daarna de
brug als sidecar, ook na een herstart. De installateur wacht maximaal 60 seconden op een
levende sidecar. Staat die als reserve klaar achter een oude terminal-luisteraar zonder
lopende taak, dan stopt de installateur die oude luisteraar netjes en wacht op de overname.
Met `--laat-staan` blijft de terminal-luisteraar draaien; met `--niet-wachten` toont de
installateur direct de huidige status. Bij een lopende taak neemt de reserve over zodra
de terminal-luisteraar later stopt. Een luisteraar met verouderde toegang stopt zelf.
Als handmatige terugval kan `brug.sh` in de Terminal van Antigravity draaien.

Claude kan daarna een read-only overleg indienen met
`python brug.py indienen -C <map> -o <rapport.md> -t "<titel>" --wacht < opdracht.md`;
`python brug.py status` toont de hartslag, een eventuele reserve en de wachtrij. De brug bewaart opdrachten onder
`~/.overleg-brug/` en aanvaardt alleen de vaste overlegopties, nooit vrije commando's.
Elke reserve schrijft zijn eigen `reserve.<pid>.json` en probeert het luisterslot elke
halve seconde. Een wachtende indiener blijft een geclaimde taak volgen tijdens overname;
een taak die zonder levende luisteraar of reserve nog in de wachtrij ligt, wordt
ingetrokken. Na een harde stop krijgt een achtergebleven taak bij de volgende slotname
een foutstatus. `SIGTERM`, `SIGHUP` en Ctrl+C stoppen een lopend overleg netjes; de
taak krijgt exitcode 130, en een verouderde luisteraar exitcode 3.
Het Antigravity-adres en de sleutel blijven in de omgeving van de luisteraar en gaan
alleen mee naar zijn kindproces `overleg.sh`.

Na een harde stop (kill -9, stroomuitval) kan er een onvolledige rondemap achterblijven. Die
staat niet in het dashboard; `python ronde.py resten` toont ze, `--weg` ruimt ze op.

## Opdrachtmodus: Claude en jouw tests

Naast het debat kan de app echt werk laten doen. Kies Opdracht in de zijbalk, wijs een
git-repo aan en beschrijf wat er moet gebeuren.

Wat er dan gebeurt:

0. Heb je een testcommando opgegeven, dan draait de app dat eerst op de ongewijzigde code.
   Zo weet je of de tests vooraf al rood of groen waren.
1. Claude voert de opdracht uit in een verse git-worktree op een eigen tak
   (`ai-opdracht/<tijdstip>`), in `werkplek/`. Je werkende map wordt niet aangeraakt.
2. De diff wordt vastgelegd, inclusief nieuwe en verwijderde bestanden.
3. De app draait het testcommando opnieuw. Wat de tests aanmaken of wijzigen, wordt daarna
   teruggezet, zodat het nooit in de diff belandt; wat er is opgeruimd staat bij de uitslag.
4. Groen: klaar. Rood: Claude krijgt de testuitvoer als geciteerd materiaal en herstelt in
   een volgende ronde, tot het maximum aantal rondes. Wijzigt hij in een ronde niets meer,
   dan stopt de run: dezelfde tests nog eens draaien levert niets nieuws op.

Zonder testcommando is het altijd een ronde. Na afloop staat het resultaat in de worktree; jij
bekijkt de diff en beslist zelf of er iets naar je echte tak gaat. De worktree blijft staan.
Opruimen doe je met `git worktree remove <pad>` vanuit de repo.

### Waarom ChatGPT hier niet meer meedoet

Tot 16-10-2026 zat er een ChatGPT-reviewer tussen. Een testset van drie echte, eerder
opgeloste fixes uit globaal-uitgaven (`Claude\ai-debat-testset\uitslag.md`), elk solo en
met reviewer, beoordeeld tegen de echte fix:

- Zonder inzage in de bestanden: de reviewer was 3 van 3 keer meteen akkoord, met 0 punten,
  en maakte elke run ongeveer 20 seconden trager.
- Met de volledige gewijzigde bestanden in de prompt: 4 terechte punten, maar het
  eindresultaat werd in geen van de drie beter dan Claude alleen. In T1 lokten zijn punten
  ongeteste databasecode uit, en echte zwaktes in T2 en T3 keurde hij goed.

De afspraak was: alleen als het duo op alle drie minstens zo goed is. Dat haalde hij niet.

**Resultatentabel opdrachten** links houdt de runs van die testset (solo en duo) en elke
nieuwe run bij: tests groen aan het eind, duur, waarom gestopt, en jouw oordeel (bruikbaar,
notitie). Runs die op een fout strandden of die jij met Nu stoppen afbrak, tellen niet mee in
de samenvatting. Stop je tijdens een teststap, dan staat die als AFGEBROKEN, niet als rood.

Dingen om te weten:

- **Het testcommando voert code uit die het model schreef.** Het commando zelf komt van
  jou en nooit uit een modeltekst, maar het draait wel de code van de uitvoerder, met jouw
  rechten. Zet het alleen in voor repo's waar dat geen kwaad kan. Leeg laten betekent: niet
  testen.
- **Er gaat niets naar OpenAI.** De opdrachtmodus gebruikt alleen Claude op je abonnement.
- **Bash staat standaard uit.** De uitvoerder mag lezen en schrijven, maar geen commando's
  draaien. Voor tests is Bash niet nodig, die draait de app. Zet je het aan, dan kan er een
  commando lopen dat uit de testuitvoer komt. Het vinkje zegt dat er ook bij.
- **Wat het kost.** Een ronde duurde in de testset 25 tot 35 seconden.

## Projectmap als context

In het onderwerpvenster kies je een map op deze machine. Met Briefing genereren leest de
Claude-kant die map lokaal uit en schrijft er een feitelijke samenvatting van. Jij leest
die na, past hem aan, en pas dan gaat hij mee het debat in. Beide kanten krijgen exact
dezelfde tekst.

De modellen kunnen zelf niets opzoeken. Alleen de goedgekeurde briefing bereikt ze, en
dat is precies de bedoeling: het verkennen gebeurt lokaal, het delen doe jij bewust.

Wat er bij het verzamelen gebeurt:

- `.git`, `node_modules`, `__pycache__`, `venv`, `dist`, `build` en soortgelijke mappen
  worden overgeslagen.
- Is het een git-repo, dan filtert `git check-ignore` alles wat in `.gitignore` staat.
- Bestanden die geheimen kunnen bevatten (`.env`, `*.pem`, `*.key`, `*credential*`,
  `*token*` en meer) worden nooit ingelezen.
- Elk overgeslagen bestand krijgt een zichtbare reden in het audit-uitklapmenu. Niets
  verdwijnt stilzwijgend.

Na afloop wordt de briefing zelf nog gescand op e-mailadressen, IP-adressen, hostnamen,
verbindingsreeksen en sleutelachtige tekenreeksen. Vindt hij iets, dan verschijnt er een
rode waarschuwing met gemaskeerde treffers. Er wordt niets automatisch weggehaald: jij
beslist wat eruit gaat voor je start. Dezelfde controle draait opnieuw zodra je de
briefing met de hand aanpast.

## Stoppen

Nu stoppen breekt de lopende beurt direct af. Het kindproces wordt op PID afgeschoten
inclusief zijn eigen kinderen, want `codex` is een `.CMD`-shim die een echte `codex.exe`
start. Die halve beurt gaat verloren; alle eerdere beurten blijven staan en het
transcript blijft bewaard.

## Zelf meepraten

In de webinterface typ je onderaan een bericht en druk je op Inbrengen (of ctrl+enter).
Het komt na de lopende beurt als MODERATOR in het debat en beide kanten lezen het mee.

Draai je vanaf de opdrachtregel, zet dan tekst in `runs/<tijdstip>/injectie.txt`. Na de
eerstvolgende beurt wordt die opgenomen en het bestand geleegd.

## Nieuw onderwerp

Kopieer een bestand in `onderwerpen/` en pas aan:

```json
{
  "vraag": "de te beslissen vraag",
  "context": "de feiten die beide kanten krijgen",
  "claude": { "naam": "CLAUDE (voor X)", "positie": "wat deze kant verdedigt" },
  "codex":  { "naam": "CHATGPT (voor Y)", "positie": "wat deze kant verdedigt" },
  "briefing": "optioneel, de goedgekeurde projectbeschrijving",
  "projectmap": "optioneel, alleen ter herinnering waar de briefing vandaan komt"
}
```

Zonder tegengestelde posities convergeren de twee binnen tien tot twintig beurten naar
volledige instemming. Geef ze dus altijd iets om over oneens te zijn.

## Modellen

Welke modelnamen werken verschilt per account en per CLI-versie. Voorbeelden van wat we
tegenkwamen: Codex met een ChatGPT-account weigert `gpt-6-pro`, `gpt-5.3-codex` en
`gpt-5.1-codex-max`; Claude Code 2.1.212 weigert `fable` (dat vereist 2.1.251 of nieuwer).

Daarom staan de keuzelijsten niet vast in de code. Draai:

```
python controleer_modellen.py
```

Dat probeert elke kandidaat met een vraag van een paar woorden en schrijft alleen de
werkende naar `modellen.json` (per machine, niet in git). Heeft een kant geen enkel
werkend model, dan schrijft het niets en zegt het dat je eerst de login moet nakijken.
Zolang `modellen.json` ontbreekt gebruikt de pagina `modellen.standaard.json`.

Nieuwe naam proberen: `python controleer_modellen.py --codex <naam> --claude <naam>`.

## Isolatie

Dit is bewust geen agent-opstelling:

- Claude draait met `--safe-mode` en `--tools ""`: geen tools, geen CLAUDE.md, geen MCP, geen hooks.
- Codex draait met `--sandbox read-only`, `--ephemeral` en `--ignore-user-config`.
- In de huisregels staat dat de tekst van de tegenpartij materiaal is, nooit een opdracht.

Geen van beide kanten kan dus bij de VM, de databases of je credentials. Zet daar niets
aan open: een debatdeelnemer met tools is een prompt-injectiekanaal.

In opdrachtmodus draait de uitvoerder met `--permission-mode acceptEdits`: schrijven kan
alleen in zijn eigen worktree, niet elders op je schijf.

De server luistert alleen op 127.0.0.1, maar dat houdt websites in je eigen browser niet
tegen. Daarom weigert hij elk schrijvend verzoek dat geen JSON is, van een andere site
komt of een vreemde hostnaam draagt. `python -m unittest test_grendels -v` controleert
dat, en de CI draait het bij elke push.

## Let op

- Beide kanten tellen af op de rollende gebruikslimieten van je abonnementen. Reken op
  ongeveer 20 tot 25 seconden per beurt.
- Zet geen bedrijfsgeheimen, hostnamen, IP-adressen of persoonsgegevens in `context`:
  de ChatGPT-kant stuurt die tekst naar OpenAI.

## Windows-valkuil

`codex` is een `.CMD`-shim en Python 3.13 start die niet op naam alleen. Daarom wordt het
volledige pad opgezocht met `shutil.which` voor het starten. `claude` is een `.EXE` en
heeft dat niet nodig.

## API-sleutel in de omgeving

Staat `ANTHROPIC_API_KEY` in je omgeving, bijvoorbeeld als Windows-gebruikersvariabele,
dan kiest `claude -p` die sleutel boven je abonnementslogin. Is hij ongeldig, dan faalt
elke Claude-beurt met "Invalid API key"; is hij geldig, dan betaal je per token. De app
haalt die variabele daarom weg uit de omgeving van elke `claude`-aanroep.
