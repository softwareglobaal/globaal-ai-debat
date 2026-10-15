Verwerking van Codex-controle 4 door Claude, 15-10-2026. Hersteld in commit 54d5382.

Beslissing: Codex had in zes van de zeven punten volledig gelijk, en in D21 deels. Het herstel vervangt de
verborgen tijdelijke map door een eenvoudiger ontwerp (naam reserveren met mkdir, board.jsonl als laatste), en de
starter door een eigen bestand met een stopmerker.

| Nr | Ernst | Oordeel en meting | Herstel | Test |
|---|---|---|---|---|
| D17 | middel | gelijk: een lege map die een ander proces net aanmaakte, werd door rename vervangen (nagebootst) | naam reserveren met `mkdir` (vervangt nooit iets), dan pas het naambestand; dat noemt dus alleen een eigen ronde | test_naam_alleen_van_eigen_ronde (10 aanroepen, zelfde seconde), test_lege_map_van_ander_proces_wordt_niet_vervangen |
| D18 | middel | gelijk, uit de code | `starter.py`: groep melden, dan stopmerker nakijken, pas dan exec; de val zet de merker eerst en laat hem staan | test_gepauzeerde_starter_start_codex_niet_meer |
| D19 | middel | gelijk, uit de code | TERM aan de groep, tot 3 s wachten, dan KILL | test_kind_dat_term_negeert_wordt_alsnog_gestopt |
| D20 | laag | gelijk | resten zijn rondemappen zonder `board.jsonl` (en oude `.nieuw-*`); `ronde.py resten` toont ze, `--weg` ruimt alleen die op en alleen als ze ouder zijn dan 10 min | test_resten_zichtbaar_en_op_te_ruimen |
| D21 | laag | deels: op Windows kan de open een vervangen symlink volgen, maar de identiteitscontrole weigert vóór slot of schrijven; de symlinktests draaien op de Windows-CI wel (run 38755362512: ok, niet overgeslagen) | geen open zonder reparsepunten (zou ctypes/CreateFileW vragen voor een geval zonder gevolg); wel de volledige route getest | test_slot_vervangen_tussen_controle_en_openen |
| D22 | laag | gelijk: de thread kon na een seconde nog niet gepland zijn | testhaak `_NA_MISLUKTE_POGING`: wachten op een aantoonbaar geweigerde slotpoging | test_trage_schrijver_houdt_slot |
| D23 | laag | gelijk, tijdelijk: zolang een ronde alleen de opdracht had, stond er `Gestart: .nieuw-*`; de volgende beurt zette de echte naam | bestanden meteen in de echte map | test_volledige_ronde (naam meteen na nieuw) en de onderbrekingstest |

Gemeten:
- 46 tests groen, ook met `-W error::ResourceWarning`; drie keer na elkaar groen.
- Mutatiecontrole in een kopie: acht mutaties, alle gevangen.
- Zelftest van codex.sh v1.5 met de echte Codex geslaagd; `ronde.py resten` vindt niets in de echte `runs/`.

Open: of er een ronde 5 komt, beslist Mehdi.
