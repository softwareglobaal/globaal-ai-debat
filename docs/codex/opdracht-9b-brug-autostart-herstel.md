# Opdracht O9b - herstel na de toets (Codex maakt, Claude controleert)

Zelfde worktree `~/dev/_codex-brug-autostart`, tak `codex/brug-autostart`, met jouw werk van O9 er al in (niet
gecommit; Claude paste in `test_brug.py` twee dingen aan: in de CI faalt een geblokkeerde loopbackpoort in plaats van
over te slaan, en `test_slechte_meting_claimt_geen_opdracht` wacht nu op de tweede 403-meting in plaats van een sleep).
Zelfde regels als O9: alleen in deze worktree schrijven, niets in `~/.gemini`, `~/.overleg-brug`, `~/Library` of de
hoofdrepo, nooit omgeving of geheugen van andere processen lezen, alleen standaardbibliotheek, niet committen.

Het driehoeksoverleg (ronde `20261017-160743-codex`, rapport `docs/codex/overleg-9-brug-autostart-toets.md`) gaf
NO-GO, 3-0 met Claude erbij. Herstel deze punten, elk met een gerichte test:

## 1. Stoppen laat geen overleg doordraaien

- `brug.py luister`: vang `SIGTERM` en `SIGHUP` op (POSIX) en behandel ze als een nette stop, net als Ctrl+C: het
  lopende overleg stoppen, de taak een eindstatus geven (`fout`, exitcode 130 of 143, reden `Luisteraar gestopt`),
  hartslag weg, slot los. Antigravity stopt of herstart een sidecar met een signaal; dan mag er niets blijven hangen.
- `debat._draai` stopt nu alleen bij een time-out het kind. Laat het bij elke uitzondering (`BaseException`, dus ook
  `KeyboardInterrupt`) het kind stoppen met `stop_proces` en daarna pas doorgooien. Controleer of `overleg.py`
  (`roep_codex_in_map` en de Gemini-route) en `codex.sh`/`starter.py` op dezelfde manier kinderen in eigen
  procesgroepen starten, en zorg dat ook die bij een stop meegaan.
- `overleg.py main`: vang op POSIX `SIGTERM` en `SIGHUP` op en zet ze om in `KeyboardInterrupt`, zodat de opruiming
  hierboven loopt. Exitcode bij zo'n stop: 130 of 143, kies en documenteer.
- `brug._stop_procesgroep`: geef het overleg genoeg tijd om zijn eigen kinderen te stoppen (bv. 5 s) voor `SIGKILL`.
- Bij het nemen van het luisterslot: taken die nog in `bezig/` staan zijn van een luisteraar die weg is. Geef ze een
  eindstatus in `fout/` (exitcode 3, reden `Afgebroken: vorige luisteraar stopte`), zodat een wachtende indiener een
  antwoord krijgt en de taak niet stil blijft hangen.
- Test: een nep-overleg dat een kleinkind in een EIGEN procesgroep/sessie start (zoals debat.py doet) en een
  pid-bestand schrijft; stuur de luisteraar `SIGTERM` tijdens de taak; bewijs dat het kleinkind binnen enkele
  seconden weg is, de taak in `fout/` staat, hartslag weg en slot vrij. Zelfde bij exit 3 (verouderd tijdens een taak).
  En: een verweesde taak in `bezig/` krijgt bij de start van een nieuwe luisteraar een eindstatus.

## 2. Overdracht naar de reserve zonder gat

- Een reserve (`--wacht-op-slot`) schrijft `reserve.json` (pid, starttijd, laatste_tik, versie, bron; geen adres of
  token) en probeert het slot elke 0,5 s in plaats van elke 5 s. Bij overname haalt hij `reserve.json` weg en schrijft
  meteen `hartslag.json`. Meerdere reserves mogen; elk eigen bestand of een veilige aanpak, kies en leg uit.
- `brug_leeft()` is waar als de hartslag leeft OF een reserve leeft (dan staat er binnen een seconde een luisteraar
  klaar zodra het slot vrijkomt). Zelfde geldigheid (60 s, pid leeft). `overleg.sh` en `overleg.py` gebruiken
  `brug_leeft()` al voor de voorcontrole en profiteren zo mee.
- `dien_in --wacht`: draait de brug niet meer terwijl de taak nog in `wachtrij/` ligt, trek de taak dan atomisch in
  (verplaatsen naar `fout/` met status `fout`, exitcode 2, reden `Ingetrokken: brug draait niet`) en meld
  `geen_brug()`. Lukt intrekken niet omdat een luisteraar ze al nam, blijf dan wachten op de eindstatus (die komt door
  punt 1 altijd), met een bovengrens: 120 s zonder levende brug of reserve, dan `geen_brug()` met het opdracht-id.
- Test: een indiener met `--wacht` terwijl de eerste luisteraar stopt en een reserve overneemt: de indiener krijgt het
  rapport en exit 0, en er draait maar één keer een overleg. En: zonder brug wordt een ingediende taak ingetrokken
  en draait ze later niet alsnog als er een luisteraar start.

## 3. Geheimen ook met spaties eromheen afgeschermd

- `geheimen_weg`: vervang zowel de ruwe waarde als de waarde na `strip()` (en de JSON-escape van beide). Test met
  adres en token met spaties eromheen dat ze nergens in uitvoer, log, status of hartslag staan.

## 4. Eén hapering blokkeert het werk niet

- Staat er een taak klaar en was de laatste meting slecht (maar nog geen 3 op rij), meet dan opnieuw, hoogstens één
  keer per seconde, in plaats van te wachten op de volgende periodieke meting. `--eenmalig` stopt niet zolang er een
  taak klaarstaat en de luisteraar niet verouderd is.
- Test: één slechte meting, daarna weer goed: de taak wordt binnen een paar seconden verwerkt.

## 5. Overgang vanaf de luisteraar die nu draait (installeer_sidecar.sh)

Nu draait al een luisteraar met de OUDE code (zonder toegangscontrole) uit een terminal. Na een herstart van Antigravity
zou die het slot blijven houden met oude gegevens, en de sidecar bleef dan voor altijd reserve. Daarom:
- Na het schrijven van `sidecar.json` wacht het script (tot 60 s, `--niet-wachten` slaat over) op een levende
  sidecar, als hoofd (`hartslag.json` bron `sidecar`) of als reserve (`reserve.json` bron `sidecar`).
- Is de sidecar reserve en is de hoofdluisteraar een terminal-luisteraar (`bron` `terminal` of geen `bron`, dus oude
  versie) en is `bezig/` leeg, stop die dan netjes met `SIGINT` naar de pid uit `hartslag.json`, maar alleen als
  `ps -o command= -p <pid>` toont dat het `brug.py luister` is (alleen de opdrachtregel, nooit de omgeving). Wacht
  daarna tot de sidecar hoofd is. Is er een taak bezig, wacht dan tot die klaar is (bovengrens 3 uur is te lang voor
  het script: meld dan dat de sidecar overneemt zodra de taak klaar is, en laat een opvolging over aan een herhaalde
  run van het script). `--laat-staan` slaat dit overnemen over.
- Meldingen in gewone taal: `Sidecar draait`, `Sidecar staat klaar als reserve en neemt over zodra de vorige
  luisteraar stopt`, `Oude luisteraar gestopt; sidecar heeft overgenomen`, of `Zet 'overleg-brug' aan in
  Antigravity: Automations`. Exit 0 in deze gevallen.
- Tests met een nep-hoofdluisteraar (een eigen proces met `brug.py luister` in de opdrachtregel) en een nep-sidecar
  (reserve met `ANTIGRAVITY_SIDECAR_WEB_PORT` gezet), in een tijdelijke `ANTIGRAVITY_CONFIG_DIR` en `OVERLEG_BRUG_MAP`.
  Ook: een proces waarvan de opdrachtregel NIET `brug.py luister` is, wordt nooit gestopt.

## Klaar betekent

- `/Users/mehdichegini/dev/globaal-ai-debat/.venv/bin/python -m unittest test_grendels test_ronde test_codex_sh
  test_meting test_overleg test_brug -v` groen (meld welke tests je sandbox niet kon draaien; Claude draait ze dan).
- `bash -n` op alle `.sh`, `git diff --check` schoon. Werk `CLAUDE.md` en `README.md` bij waar het gedrag veranderde.
- Kort Nederlands antwoord: per punt wat je deed en welke test het bewijst, en wat je bewust anders deed met reden.
