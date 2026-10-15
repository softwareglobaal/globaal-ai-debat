Verwerking van Codex-controle 2 door Claude, 15-10-2026. Hersteld in commit 6067cdc.

Beslissing: Codex had weer in alle punten gelijk. De herstellingen van ronde 1 hadden zelf fouten: het eigen
slot met een verlooptijd (D08, D09) en de plaats van de signaalval (D10, D11). Het herstel pakt nu de oorzaak:
een slot van het besturingssysteem en een uitkomst per ronde, afgedwongen in ronde.py.

| Nr | Ernst | Oordeel en meting | Herstel | Test |
|---|---|---|---|---|
| D03 | (rest) | gelijk: de test dwong geen overlap af | testhaak `_NA_LEZEN` houdt een schrijver binnen het slot vast | test_trage_schrijver_houdt_slot |
| D05 | (rest) | gelijk: alleen een signaal aan de hele groep, na het aanmaken, was getest | zie D10 en D11 | drie nieuwe signaaltests |
| D07 | (rest) | gelijk: de grendel was te omzeilen | zie D12; plus een live weergave met kwaadaardige namen | test_grendel_vangt_elke_omweg |
| D08 | hoog | gelijk, uit de code: na 60 s pakte een tweede proces het slot af; `rmdir` in `finally` kon andermans slot weghalen | `flock` (POSIX) en `msvcrt.locking` (Windows) op `.slot`; geen verlooptijd, het OS geeft vrij bij exit | test_slot_van_gecrasht_proces_komt_vrij, test_slot_van_levende_houder_wordt_niet_afgepakt |
| D09 | middel | gelijk: een oude niet-lege slotmap liet een beurt na 15 s nog draaien (wachttijd 10 s) | een `.slot` die geen gewoon bestand is, of een symlink: meteen ValueError | test_vreemd_slot_geweigerd_zonder_te_hangen |
| D10 | middel | gelijk, uit de code | val vóór het aanmaken; `--naambestand` zodat de naam er meteen is; Codex via `setsid` in een eigen groep, de val stopt de hele groep, ook in het venster vlak na de start | test_signaal_aan_script_stopt_codex_en_kinderen, test_signaal_tijdens_aanmaken_ronde |
| D11 | middel | gelijk, uit de code | ronde.py weigert een tweede uitkomst en een verwerking zonder uitkomst; de fouttak geeft code 3 als ook de fout niet in het dashboard kwam | test_signaal_na_antwoord_geen_tweede_uitkomst, test_een_uitkomst_per_ronde, test_codex_faalt_en_dashboard_faalt_geeft_code_3 |
| D12 | middel | gelijk: `innerHTML +=` werd niet gezien | elke `innerHTML` moet `= <vaste tekst>;` zijn; `outerHTML`, `insertAdjacentHTML`, `document.write` en verwanten verboden | test_pagina_heeft_geen_html_uit_variabelen, test_grendel_vangt_elke_omweg |

Gemeten:
- 36 tests groen, ook met `-W error::ResourceWarning`; de tijdgevoelige tests drie keer na elkaar groen.
- Mutatiecontrole in een kopie: elke nieuwe test faalt als de fout teruggezet wordt (geen echt slot, vreemd slot
  aanvaard, tweede uitkomst aanvaard, fouttak zonder controle, val na het aanmaken, geen groepsstop).
- Live in het dashboard: een run met een titel, spreker en bestandsnaam vol HTML toont alles als tekst; er
  ontstond geen enkel element en het script liep niet. De proefrun is daarna weggehaald.

Open: ronde 3, de hercontrole van deze herstellingen.
