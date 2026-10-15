Verwerking van Codex-controle 1 door Claude, 15-10-2026. Hersteld in commit c557bdd.

Beslissing: Codex had in alle zeven punten gelijk. Elk punt is nagemeten, hersteld in de bron en vastgezet met
een test die faalt op de oude code (gecontroleerd door de oude code terug te zetten in een kopie).

| Nr | Ernst | Oordeel en meting | Herstel | Test |
|---|---|---|---|---|
| D01 | hoog | gelijk: pagina.html:423 zette bestandsnamen via innerHTML; ook :456 deed dat met een naam | beide via DOM en textContent | test_ronde.PaginaGrendel: innerHTML mag alleen vaste tekst krijgen |
| D02 | middel | gelijk: een symlink in runs/ liet `beurt` buiten runs/ schrijven (nagebootst) | `_geen_symlinks`: ronde en bestanden geen symlink, opgelost pad in runs/ | test_symlink_geweigerd |
| D03 | middel | gelijk, uit de code; bewezen met twee processen | slot per ronde (atomische mkdir, wacht 10 s, verlopen na 60 s) | test_gelijktijdige_beurten_elk_een_nummer (2 x 15 beurten) |
| D04 | middel | gelijk: `codex.sh -C` liep na 3 s nog (oneindige lus) | `waarde()` vóór elke `shift 2`: code 2 met melding | test_optie_zonder_waarde_stopt (alle zeven opties) |
| D05 | middel | gelijk, uit de code | Codex op de achtergrond met `wait` en een val op INT/TERM/HUP: Codex stoppen, FOUT-beurt, code 130; dashboardfout geeft code 3 | test_onderbreken_markeert_fout, test_dashboard_faalt_geeft_code_3 |
| D06 | laag | gelijk: `--duur nan` schreef NaN in board.jsonl | eindig en niet negatief, `allow_nan=False` | test_duur_eindig_en_niet_negatief |
| D07 | middel | gelijk | codex.sh staat nu in deze repo (~/.claude/tools/codex.sh is een symlink); test_codex_sh.py met een nep-Codex; beide testbestanden in de CI | zie hierboven |

Over Codex' afsluiting: de tests konden in de alleen-lezen-sandbox niet draaien (geen tijdelijke map). Claude
draaide ze zelf: 27 tests groen, ook met `-W error::ResourceWarning`; de zelftest van codex.sh slaagt.

Open: ronde 2, waarin Codex de herstellingen zelf naleest.
