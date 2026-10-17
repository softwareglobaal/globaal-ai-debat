# Opdracht O4 - de overleg-brug (Codex maakt, Claude controleert)

Repo-worktree `~/dev/_overleg-brug`, tak `overleg-brug`, gebaseerd op origin/main 974b9e6.
Lees eerst `CLAUDE.md` en `README.md` van de repo en volg die. Niet committen of pushen: Claude doet dat.

## Waarom

`overleg.sh` (driehoeksoverleg Codex + Gemini + Claude-verwerking) werkt alleen vanuit de Terminal van
Antigravity: alleen daar staan `ANTIGRAVITY_LS_ADDRESS` en `ANTIGRAVITY_CSRF_TOKEN` in de omgeving. Claude kan dus
niet zelf een overleg starten. Mehdi besliste op 17-10-2026: bouw een brug. Mehdi start één keer (per dag) met één
regel een luisteraar in de Terminal van Antigravity. Daarna legt Claude opdrachten in een vaste map en de luisteraar
voert ze uit met de toegang van Antigravity. **De sleutel verlaat Antigravity nooit**: geen bestand, geen log, geen
status, geen run bevat ooit adres of token, en de luisteraar geeft ze alleen door aan het kindproces `overleg.sh`.

## Wat te bouwen

1. **`brug.py`** (Python, standaardbibliotheek, werkt op macOS en Linux; Windows mag de luisteraar weigeren maar de
   tests moeten daar slagen of netjes overslaan), met subcommando's:
   - `luister`: de luisteraar. Weigert te starten (exit 2, duidelijke Nederlandse melding) als de
     Antigravity-omgeving ontbreekt. Eén luisteraar tegelijk (OS-slot, zoals ronde.py dat doet). Kijkt elke paar
     seconden in de wachtrij, neemt de oudste opdracht atomisch in behandeling (rename), voert ze uit, schrijft
     de uitkomst. Eén opdracht tegelijk. Schrijft een hartslagbestand (pid, starttijd, laatste tik, versie) zodat
     Claude kan zien of de brug leeft. Stopt netjes op Ctrl+C en ruimt de hartslag op. `--eenmalig` voor tests:
     verwerk wat er ligt en stop.
   - `indienen`: voor Claude. Maakt een opdracht aan (eerst `.tmp`, dan rename), met: werkmap (-C), rapport (-o),
     titel, opdrachttekst (uit een bestand of stdin) en toegestane opties. `--wacht` wacht tot klaar of fout en
     geeft dan exitcode en rapportpad; zonder `--wacht` alleen de opdracht-id. Weigert in te dienen als de
     hartslag ouder is dan 60 s (brug draait niet), met de melding wat Mehdi moet doen.
   - `status`: leeft de brug, wat staat in de wachtrij, wat is bezig, laatste uitkomsten.
2. **Wachtrijmap**: standaard `~/.overleg-brug/` (instelbaar met `OVERLEG_BRUG_MAP`), rechten 0700, submappen
   `wachtrij/`, `bezig/`, `klaar/`, `fout/`. Per opdracht een JSON-bestand en een statusbestand; de uitvoer van
   `overleg.sh` (stdout+stderr) in een logbestand naast de status.
3. **Strenge toetsing van elke opdracht vóór uitvoering** (afwijzen = naar `fout/` met reden, niets uitvoeren):
   - alleen bekende velden; opties alleen uit een witte lijst: `b`, `m`, `e`, `g`, `G`, `c`, `E`, `T`,
     `met_claude`, elk met een strak patroon (getallen in een bereik, modelnamen `[a-z0-9._-]+`, niveaus uit een
     vaste lijst). Geen vrije extra vlaggen.
   - werkmap moet een bestaande map onder `$HOME` zijn; rapport moet onder `$HOME` liggen en op `.md` eindigen;
     geen symlinks in het opdrachtbestand zelf; opdrachtbestand eigendom van de huidige gebruiker en niet
     schrijfbaar voor anderen.
   - opdrachttekst niet leeg en begrensd (bv. 200 kB).
   - uitvoeren met een argumentlijst (nooit via een shell), opdrachttekst via stdin, cwd = werkmap.
4. **Uitvoering**: roept `overleg.sh` uit dezelfde repo aan (pad instelbaar met `OVERLEG_BRUG_OVERLEG` voor
   tests). De omgeving van het kindproces is die van de luisteraar (dus mét de Antigravity-gegevens); niets
   daarvan wordt weggeschreven. Een totale tijdslimiet per opdracht (standaard 3 uur) en stoppen van de hele
   procesgroep bij overschrijding.
5. **Startregel voor Mehdi**: `brug.sh` (gitignored zoals overleg.sh? Nee: dit is nieuw; zet het in git, en voeg
   het niet toe aan de .gitignore) die de venv-python van de repo gebruikt, de Antigravity-omgeving controleert en
   `brug.py luister` start met een duidelijke regel "Brug draait, laat dit venster open". Mehdi plakt dan alleen:
   `~/dev/globaal-ai-debat/brug.sh`
6. **Tests** `test_brug.py` (in CI, toevoegen aan `.github/workflows/grendels.yml`): weigering zonder
   Antigravity-omgeving; witte lijst (onbekend veld, onbekende optie, shell-tekens in een waarde, pad buiten
   `$HOME`, symlink, vreemde eigenaar of wereldschrijfbaar waar het platform dat toelaat); atomisch claimen
   (twee luisteraars of twee claims: één wint); volledige ronde met een stub-`overleg.sh` die controleert dat hij
   de Antigravity-variabelen krijgt en een rapport schrijft; nergens in wachtrij, status of log staat de
   tokenwaarde (test met een herkenbare nepsleutel); hartslag verloopt; `indienen --wacht` geeft de juiste
   exitcode; tijdslimiet stopt de stub. Gebruik alleen tijdelijke mappen, nooit `~/.overleg-brug` of echte runs.
7. **Documentatie**: korte paragraaf in `README.md` en de bestandstabel in `CLAUDE.md`: wat de brug is, de
   startregel, dat de sleutel in Antigravity blijft, en dat een lokale opdracht alleen read-only overleg kan
   starten (geen vrije commando's).

## Grenzen

Alleen bestanden in deze worktree. Geen netwerk, geen echte Codex-, Gemini- of Claude-oproep. Haal nooit een sleutel
uit processen, logs of de Keychain. Bestaand gedrag van overleg.sh, codex.sh en ronde.py niet veranderen.

## Afronding

Draai `TMPDIR=$(mktemp -d) ~/dev/globaal-ai-debat/.venv/bin/python -m unittest test_grendels test_ronde
test_codex_sh test_meting test_overleg test_brug`, plus `git diff --check` en `bash -n brug.sh`.
Antwoord kort in het Nederlands: wat je bouwde (`bestand:regel`), de testuitslag, en wat open blijft.
