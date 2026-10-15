**Beslissing: niet klaar.** De ronde kan bij een onderbreking tijdens het aanmaken nog onvolledig in het dashboard belanden. Ook is de stop van Codex niet betrouwbaar wanneer de gekozen Python via een shellwrapper start.

D08: hersteld. D09: hersteld voor een al aanwezig vreemd slot; zie D15 voor Windows. D10: niet volledig. D11: hersteld. D12: hersteld. Van de eerdere restpunten is D03 in de code hersteld, maar de test nog tijdsafhankelijk (D16); D05 blijft open via D10; D07 is hersteld.

1. **D13 — middel — [ronde.py:201](/Users/mehdichegini/dev/globaal-ai-debat/ronde.py:201), [test_codex_sh.py:49](/Users/mehdichegini/dev/globaal-ai-debat/test_codex_sh.py:49).** Bij Ctrl-C aan de procesgroep kan `nieuw` stoppen nadat `board.jsonl` bestaat maar vóór het naambestand is geschreven. De val kent de ronde dan niet; na het naambestand maar vóór OPDRACHT kan zij zelfs FOUT als eerste beurt schrijven. De test pauzeert pas *nadat* `nieuw` klaar is. Maak de eerste beurt gereed vóór de ronde zichtbaar wordt en test signalen tijdens die schrijfstappen.

2. **D14 — middel — [codex.sh:126](/Users/mehdichegini/dev/globaal-ai-debat/codex.sh:126), [codex.sh:156](/Users/mehdichegini/dev/globaal-ai-debat/codex.sh:156).** Als `$PY` een shellwrapper is, verwijst `$!` naar die wrapper, terwijl `setsid()` in diens Python-kind een groep met een ander ID maakt. De groepsstop mist dan Codex; de terugval stopt alleen de wrapper. De actieve-Codex-test gebruikt rechtstreeks `sys.executable`. Leg het werkelijke groeps-ID vast en test een signaal terwijl Codex via een wrapper draait.

3. **D15 — laag — [ronde.py:103](/Users/mehdichegini/dev/globaal-ai-debat/ronde.py:103).** Op Windows valt `O_NOFOLLOW` weg. Wisselt een ander lokaal proces `.slot` tussen de symlinkcontrole en `os.open()` voor een symlink naar buiten `runs/`, dan volgt de open die alsnog. Open het Windows-slot zonder reparse points te volgen en controleer het geopende object.

4. **D16 — laag — [test_ronde.py:139](/Users/mehdichegini/dev/globaal-ai-debat/test_ronde.py:139).** De houder slaapt twee seconden na het teken. Wordt de tweede schrijver pas daarna ingepland, dan kan de test ook zonder werkend slot slagen. Gebruik een vrijgavebarrière in plaats van een vaste slaapduur.

**Afsluiting**

1. **Gedaan:** werkafspraken v1.2, commit `da2c152`, diff `9b9e74d..da2c152`, code, tests en CI-configuratie gelezen; niets gewijzigd of verstuurd.
2. **Nagekeken:** 36 testmethoden en een CI-matrix voor macOS, Linux en Windows staan in de repo. Tests, CI-run `38753120119`, de mutatieproeven en de live weergave kon ik in deze leessandbox niet zelfstandig verifiëren.
3. **Open:** Claude herstelt D13–D16 in de bron en laat vooral de signalen tijdens het daadwerkelijke aanmaken en via een Python-wrapper opnieuw controleren.