**Niet klaar.** D01, D02, D04 en D06 zijn hersteld; D03, D05 en D07 nog niet volledig.

| Punt | Hercontrole van herstel en test |
|---|---|
| D01 | Hersteld: bestandsnamen en de naam van de actieve schrijver komen als tekst op de pagina. De test vangt de oude `innerHTML =`-code, maar rendert geen kwaadaardige bestandsnaam. |
| D02 | Hersteld: de test vangt symlinks naar een ronde of transcript buiten `runs/`. |
| D03 | Niet volledig: de test controleert twee gelijktijdige schrijvers, maar geen verlopen slot of crash. Zonder afgedwongen overlap kan de oude race de test soms passeren. |
| D04 | Hersteld: Bash 3.2 accepteert de code; de test vangt ontbrekende optiewaarden. |
| D05 | Niet volledig: de tests dekken een mislukte dashboardstap en één onderbreking nadat de ronde is aangemaakt. Signalen op andere momenten blijven ongetest. |
| D06 | Hersteld: `NaN`, oneindig en negatieve duur worden geweigerd; de test vangt dit. |
| D07 | Niet volledig: CI roept de shelltests aan, maar de HTML-grendel is te omzeilen. |

1. **D08 — hoog — [ronde.py:75](/Users/mehdichegini/dev/globaal-ai-debat/ronde.py:75).** Na 60 seconden verwijdert een tweede proces het slot, ook als de eerste schrijver nog bezig is. Beide kunnen dan hetzelfde beurtnummer berekenen; de eerste kan bij afsluiten zelfs het nieuwe slot verwijderen. Gebruik een OS-bestandsslot dat bij procesexit vrijkomt, ook op Windows. Test een schrijver die langer dan 60 seconden vasthoudt en een gecrasht proces.

2. **D09 — middel — [ronde.py:80](/Users/mehdichegini/dev/globaal-ai-debat/ronde.py:80).** Een oude `.slot`-symlink of niet-lege slotmap laat `rmdir` falen. `continue` slaat vervolgens zowel de wachttijd als de deadline over: `beurt` draait onbeperkt rond. Weiger zo’n slot en controleer de deadline ook na een opruimfout; test die gevallen, waaronder een toegangsweigering op Windows.

3. **D10 — middel — [codex.sh:119](/Users/mehdichegini/dev/globaal-ai-debat/codex.sh:119).** De signaalval wordt pas na `ronde nieuw` geïnstalleerd. Een `TERM` tijdens het aanmaken kan een ronde met alleen OPDRACHT achterlaten. Na de start van het achtergrondproces is er bovendien een kort venster vóór `CPID=$!`; dan kan Codex blijven draaien. Installeer de val vóór rondecreatie, beheer de hele procesgroep en test een direct signaal aan het script in beide fasen. De huidige test signaleert de *hele* procesgroep en toont dus niet aan dat de val kinderen opruimt.

4. **D11 — middel — [codex.sh:151](/Users/mehdichegini/dev/globaal-ai-debat/codex.sh:151).** Komt een signaal nadat `ronde beurt` CONTROLE of FOUT heeft geschreven maar vóór `AFGESLOTEN=1`, dan schrijft de val nog een FOUT. De fouttak controleert ook niet of haar dashboardbeurt slaagde. Maak het eindresultaat per ronde eenmalig en controleer beide schrijfresultaten; test een signaal tijdens het vastleggen.

5. **D12 — middel — [test_ronde.py:158](/Users/mehdichegini/dev/globaal-ai-debat/test_ronde.py:158).** De grendel zoekt alleen `.innerHTML =`. `regel.innerHTML += f.toegevoegd.join(", ")` wordt niet gevonden en zou HTML uit een bestandsnaam uitvoeren. Voeg een rendertest met een kwaadaardige bestandsnaam toe en bewaak ook andere HTML-invoegmethoden.

**Afsluiting**

1. **Gedaan:** werkafspraken v1.2, `git status`, `git log`, `git diff b529b70..9b9e74d`, code en tests gelezen. Niets gewijzigd of gecommit.
2. **Nagekeken:** `bash -n codex.sh` op Bash 3.2 en `git diff --check` slagen. Er zijn 27 testmethoden; de claim dat ze groen zijn én op oude code falen kon ik in deze lees-sandbox niet uitvoeren.
3. **Open:** Claude herstelt D08–D12, voegt de genoemde grendels toe en laat daarna een nieuwe leescontrole doen.