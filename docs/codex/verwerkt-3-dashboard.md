Verwerking van Codex-controle 3 door Claude, 15-10-2026. Hersteld in commit a36f8dd.

Beslissing: Codex had weer in alle punten gelijk. Deze keer zijn eerst de tests geschreven en op de oude code
gedraaid; wat zij vingen, was de meting.

| Nr | Ernst | Oordeel en meting | Herstel | Test |
|---|---|---|---|---|
| D13 | middel | gelijk: op da2c152 werd FOUT als eerste beurt aanvaard (test faalde); een ronde was zichtbaar voor ze af was | `nieuw` bouwt in `runs/.nieuw-*` en hernoemt atomisch; een beurt in een ronde zonder opdracht vooraan wordt geweigerd; `/api/runs` slaat verborgen mappen over | test_onderbroken_aanmaken_laat_geen_halve_ronde (SIGINT na elke stap), test_uitkomst_nooit_als_eerste_beurt |
| D14 | middel | gelijk: via een python-wrapper draaiden Codex en zijn kind nog na het signaal (test faalde, pids 82902 en 82905) | de starter schrijft na `setsid` zijn pid (= groep) naar een tijdelijk bestand; de val stopt de starter en daarna die groep | test_signaal_stopt_codex_ook_via_python_wrapper |
| D15 | laag | gelijk, uit de code (Windows heeft geen O_NOFOLLOW) | aanmaken alleen met O_EXCL, anders openen zonder O_CREAT; het geopende bestand moet `.slot` zelf zijn (fstat tegen lstat) | test_geopend_slot_moet_het_bestand_zelf_zijn |
| D16 | laag | gelijk: de test kon zonder slot slagen bij ongelukkige planning | barrière: de houder blijft binnen tot de test hem loslaat; de tweede schrijver moet op dat moment nog wachten | test_trage_schrijver_houdt_slot |
| D10 | (rest) | zie D14 | | |

Gemeten:
- 40 tests groen, ook met `-W error::ResourceWarning`; de tijdgevoelige tests drie keer na elkaar groen.
- Mutatiecontrole in een kopie: elke nieuwe test faalt als de fout teruggezet wordt.
- Zelftest van codex.sh v1.4 met de echte Codex geslaagd; geen verborgen resten in `runs/`.

Open: ronde 4, de hercontrole van deze herstellingen.
