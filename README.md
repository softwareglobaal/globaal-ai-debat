# ai-debat

Laat Claude en ChatGPT met elkaar praten op de abonnementen, zonder API-keys.

- Claude-kant: `claude -p` via Claude Code, draait op het Claude-abonnement.
- ChatGPT-kant: `codex exec` via Codex CLI, draait op het ChatGPT-abonnement.
- De orkestrator wisselt de beurten af, schrijft alles weg en dwingt de limieten af.

Twee modi: **Debat** (twee modellen verdedigen een tegengestelde positie) en **Opdracht**
(Claude schrijft code in een git-worktree, ChatGPT reviewt de diff, Claude herziet).

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
| `--stop-bij-instemming` | stop zodra er twee beurten achtereen wordt ingestemd |

## Resultaat

Per run komt er een map in `runs/<tijdstip>/`:

- `board.jsonl` - één regel per beurt met spreker, model, tijdstip, duur en tekst
- `transcript.md` - leesbaar verslag
- `onderwerp.json` - kopie van het gebruikte onderwerp
- `injectie.txt` - zie hieronder

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

Na een harde stop (kill -9, stroomuitval) kan er een onvolledige rondemap achterblijven. Die
staat niet in het dashboard; `python ronde.py resten` toont ze, `--weg` ruimt ze op.

## Opdrachtmodus: uitvoerder en reviewer

Naast het debat kan de app echt werk laten doen. Kies Opdracht in de zijbalk, wijs een
git-repo aan en beschrijf wat er moet gebeuren.

Wat er dan gebeurt, per ronde:

1. Claude voert de opdracht uit in een verse git-worktree op een eigen tak
   (`ai-opdracht/<tijdstip>`), in `werkplek/`. Je werkende map wordt niet aangeraakt.
2. De diff wordt vastgelegd, inclusief nieuwe en verwijderde bestanden.
3. ChatGPT krijgt de opdracht, het verslag en de diff, mag de omliggende code lezen maar
   niets schrijven, en levert bevindingen.
4. Claude krijgt die bevindingen als geciteerd materiaal terug en herziet.

Zet het aantal rondes op 2 of 3. Na afloop staat het resultaat in de worktree; jij bekijkt
de diff en beslist zelf of er iets naar je echte tak gaat. De worktree blijft staan.
Opruimen doe je met `git worktree remove <pad>` vanuit de repo.

Twee dingen om te weten:

- **Bash staat standaard uit.** De uitvoerder mag lezen en schrijven, maar geen commando's
  draaien. Daardoor kan hij ook geen tests draaien. Zet je het aan, dan kan er een commando
  lopen dat uit de tekst van de reviewer komt. Het vinkje zegt dat er ook bij.
- **Dit kost veel.** Een uitvoerbeurt duurde in de test ongeveer 50 seconden en is een
  veelvoud van een gespreksbeurt. Twee rondes is vier beurten.

De tekst van de reviewer komt altijd binnen tussen expliciete grensmarkeringen, met de
instructie dat het materiaal is en geen opdracht. Dat is geen sluitende bescherming, maar
het is de reden dat Bash standaard uit staat.

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
