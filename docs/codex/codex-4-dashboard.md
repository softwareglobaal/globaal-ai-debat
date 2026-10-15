**Beslissing: niet klaar.** D13 is niet volledig hersteld: een halve ronde wordt niet meer zichtbaar, maar naamraces en harde stops blijven open. D14 werkt voor de geteste Python-wrapper, maar de stopval is niet betrouwbaar in alle gevallen. D15 is niet volledig hersteld; D16 blijft tijdsafhankelijk.

1. **D17 — middel — [ronde.py:241](/Users/mehdichegini/dev/globaal-ai-debat/ronde.py:241), [codex.sh:142](/Users/mehdichegini/dev/globaal-ai-debat/codex.sh:142).** Twee aanroepen kunnen dezelfde naam vóór `rename` in hun `.ronde`-bestand schrijven. Wordt de verliezer onderbroken, dan kan zijn val `FOUT` aan de ronde van de winnaar toevoegen. Op POSIX kan `rename` bovendien een tussentijds aangemaakte lege doelmap vervangen. Publiceer met een atomische *niet vervangen* operatie en controleer vóór `FOUT` of de ronde bij deze aanroep hoort.

2. **D18 — middel — [codex.sh:130](/Users/mehdichegini/dev/globaal-ai-debat/codex.sh:130).** Na twee seconden geeft de val het wachten op het groeps-ID op. Pauzeert Python tussen het openen en schrijven van het groepsbestand, dan kan het na afloop alsnog Codex starten. Synchroniseer registratie en annulering; test precies die pauze.

3. **D19 — middel — [codex.sh:132](/Users/mehdichegini/dev/globaal-ai-debat/codex.sh:132).** De val stuurt alleen `TERM` en wacht niet op beëindiging. Een kind dat `TERM` negeert blijft draaien terwijl de ronde `FOUT` krijgt. Controleer het einde van de groep en escaleer zo nodig; test met zo’n kind.

4. **D20 — laag — [ronde.py:258](/Users/mehdichegini/dev/globaal-ai-debat/ronde.py:258), [web.py:459](/Users/mehdichegini/dev/globaal-ai-debat/web.py:459).** `SIGKILL` en Windows `terminate()` slaan de opruiming over. Een `.nieuw-*`-map met opdrachtgegevens blijft verborgen op schijf; de test accepteert dat. Maak resten zichtbaar voor beheer en voorzie gecontroleerde opruiming.

5. **D21 — laag — [ronde.py:129](/Users/mehdichegini/dev/globaal-ai-debat/ronde.py:129), [test_ronde.py:211](/Users/mehdichegini/dev/globaal-ai-debat/test_ronde.py:211).** De Windows-route voor een bestaand slot kan een tussentijds geplaatste symlink nog openen; de identiteitscontrole wijst die pas daarna af. De test roept alleen die controle aan en kan zonder symlinkrechten overslaan. Test de volledige slotroute op Windows en open zonder reparsepunten te volgen.

6. **D22 — laag — [test_ronde.py:151](/Users/mehdichegini/dev/globaal-ai-debat/test_ronde.py:151).** De tweede thread kan een seconde ongepland blijven. Dan slaagt de test na vrijgave ook zonder werkend slot. Wacht op een aantoonbaar mislukte slotpoging vóór vrijgave.

7. **D23 — laag — [ronde.py:235](/Users/mehdichegini/dev/globaal-ai-debat/ronde.py:235), [debat.py:218](/Users/mehdichegini/dev/globaal-ai-debat/debat.py:218).** Het eerste transcript vermeldt `Gestart: .nieuw-*` in plaats van de definitieve rondenaam; dat staat ook in een huidige ronde. Schrijf de definitieve naam in het transcript vóór publicatie.

**Gedaan:** werkafspraken v1.2, commit `0c2fb71`, de diff, code en tests gelezen; niets gewijzigd, gecommit of verstuurd.  
**Nagekeken:** 40 testmethoden en de CI-matrix staan in de repo. D13 draait in de code ook op Windows; de shelltests worden daar overgeslagen. Tests, CI-run `38755362512`, zelftest en mutatieproeven kon ik zonder tests of netwerk niet zelfstandig bevestigen. Het tijdelijke groepsbestand is per aanroep uniek en wordt bij gewone beëindiging verwijderd.  
**Open:** Claude kan D17–D23 in de bron herstellen en met gerichte race- en Windows-tests nameten.