# Opdracht O9c - tweede herstel na de toets (Codex maakt, Claude controleert)

Zelfde worktree `~/dev/_codex-brug-autostart`, tak `codex/brug-autostart`, met O9 en O9b erin (niet gecommit; Claude
zette in `luister` de reservetik op hoogstens elke 5 s, het slot wordt nog elke 0,5 s geprobeerd). Zelfde regels:
alleen in deze worktree schrijven, niets in `~/.gemini`, `~/.overleg-brug`, `~/Library` of de hoofdrepo, nooit
omgeving of geheugen van andere processen lezen, alleen standaardbibliotheek, niet committen.

De tweede toets (ronde in `docs/codex/overleg-9b-brug-autostart-toets.md`) gaf NO-GO, 3-0 met Claude erbij. De vijf
punten van O9b zijn opgelost; deze vier randgevallen nog niet. Dit is volgens de stopregel de laatste losse
herstelronde: houd het klein en gericht, verander niets wat niet nodig is. Elk punt met een gerichte test.

## 1. Stoppen nooit midden in een bestandswissel; overname door het script zonder race

- `brug.py luister`: de handler voor `SIGINT`/`SIGTERM`/`SIGHUP` gooit geen `KeyboardInterrupt` meer maar zet een
  stop-event. De hoofdlus, het reservewachten en `_draai` (die al elke 0,2 s rondgaat) kijken naar dat event. In
  `_draai`: procesgroep netjes stoppen zoals nu (met de uitvoer bewaard) en teruggeven met exitcode 130, reden
  `Luisteraar gestopt`; `verwerk` schrijft dan de eindstatus en verplaatst de bestanden gewoon af. Daarna stopt de
  luisteraar zoals bij Ctrl+C (hartslag weg, slot los, exit 0). Een tweede signaal tijdens het stoppen wordt genegeerd.
- `installeer_sidecar.sh` overname: `kill -STOP <pid>`, dan opnieuw controleren dat de hoofdhartslag nog dezelfde
  terminal-pid heeft, `ps -o command=` nog `brug.py luister` toont, en `wachtrij/` (alleen echte taken, geen
  `.status.json`) en `bezig/` leeg zijn. Klopt alles: `kill -INT` en daarna `kill -CONT` (het signaal komt aan bij het
  hervatten). Klopt iets niet: meteen `kill -CONT` en later opnieuw proberen binnen de wachttijd. Een `trap` zorgt dat
  een gestopt proces altijd `CONT` krijgt, ook als het script zelf onderbroken wordt.
- Tests: signaal tijdens een taak geeft een nette eindstatus 130 in `fout/` met log en zonder resten in `bezig/`;
  een taak in de wachtrij tijdens de overname: geen `INT`, het oude proces draait verder (niet in toestand `T`).

## 2. Een geldige eindstatus gaat nooit verloren; een wachtende indiener blijft niet hangen

- `herstel_verweesde_taken`: staat in `bezig/` al een status met toestand `klaar` of `fout` en een geheel getal als
  exitcode, verplaats dan opdracht, log en status naar die map in plaats van ze te overschrijven met exitcode 3.
  Ruim een achtergebleven `wachtrij/<id>.status.json` op.
- `dien_in --wacht`: leeft er geen brug en geen reserve en is de taak al geclaimd, probeer dan zelf kort het
  luisterslot te nemen (zonder wachten). Lukt dat: `herstel_verweesde_taken`, slot los, en de eindstatus wordt in de
  volgende lusronde gelezen. Lukt het niet (iemand houdt het slot): blijf wachten tot de bestaande grens van 120 s.
- Tests: crash na het schrijven van de eindstatus `klaar` maar voor het verplaatsen: de opvolger bewaart `klaar` en
  exitcode 0; een indiener met `--wacht` zonder enige luisteraar krijgt bij een verweesde taak binnen enkele seconden
  een eindstatus in plaats van 120 s te wachten.

## 3. Het token gaat alleen naar deze Mac

- `brug.toegang` en `debat._antigravity_rpc` (en elke andere plek die `ANTIGRAVITY_CSRF_TOKEN` in een verzoek zet;
  zoek ze op): alleen hosts `127.0.0.1`, `localhost` of `::1` (ook `[::1]:poort`), met een poort, zonder pad,
  gebruiker of wachtwoord. Anders geen verzoek: `toegang` geeft `"weg"`, `_antigravity_rpc` een `GeminiFout` zonder
  het adres in de tekst. Beide zonder proxy (`ProxyHandler({})`) en zonder het volgen van omleidingen.
- Tests: een niet-lokaal adres en een adres met pad of gebruiker worden geweigerd zonder verzoek; met `HTTP_PROXY` gezet
  gaat het verzoek toch rechtstreeks naar de nep-server; een omleiding wordt niet gevolgd.

## 4. Nooit een signaal naar een vrijgekomen procesgroep

- `debat.stop_proces`: stuur `killpg` alleen zolang het proces nog niet is opgeruimd (`proc.returncode is None`; roep
  daarvoor NIET `poll()` aan, want die ruimt op). Een niet-opgeruimde leider (ook als zombie) houdt zijn groepsnummer
  bezet, dus dan is `killpg` veilig en raakt hij ook achtergebleven kleinkinderen. Daarna pas opruimen. Leg dat in een
  korte commentaarregel vast.
- `web.py` "Nu stoppen": laat stoppen en het registreren van het lopende proces niet racen (bv. stoppen onder hetzelfde
  slot waarmee `_draai` het proces registreert en afmeldt). Houd de wijziging klein.
- Tests: `stop_proces` op een al opgeruimd proces stuurt geen signaal (mock `os.killpg`); op een levend proces met een
  kleinkind in dezelfde groep stopt het beide.

## Klaar betekent

- `/Users/mehdichegini/dev/globaal-ai-debat/.venv/bin/python -m unittest test_grendels test_ronde test_codex_sh
  test_meting test_overleg test_brug -v` groen (meld welke tests je sandbox niet kon draaien; Claude draait ze dan).
- `bash -n` op alle `.sh`, `git diff --check` schoon; `CLAUDE.md` bijwerken waar gedrag veranderde.
- Kort Nederlands antwoord: per punt wat je deed en welke test het bewijst, en wat je bewust anders deed met reden.
