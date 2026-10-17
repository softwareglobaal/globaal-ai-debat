committen: ja na herstel.

1. **Hoog — [debat.py:174](/Users/mehdichegini/dev/globaal-ai-debat/debat.py:174).** De rechtstreekse Antigravity-aanroep verstuurt letterlijk `MODEL_PLACEHOLDER_*` als modelcode. De tests verwachten dezelfde placeholders en beproeven deze aanroep niet. Vul geverifieerde codes in en test de aanroep met een lokale server.

2. **Hoog — [debat.py:334](/Users/mehdichegini/dev/globaal-ai-debat/debat.py:334), [overleg.py:207](/Users/mehdichegini/dev/globaal-ai-debat/overleg.py:207).** Een serverantwoord op een fout wordt onbewerkt in de foutmelding gezet; die komt in `runs/`, het dashboard en stderr. Als de server een header of sleutel terugstuurt, wordt die bewaard. Toon alleen foutcode en methode; filter gevoelige gegevens uit overige fouten.

3. **Middel — [debat.py:241](/Users/mehdichegini/dev/globaal-ai-debat/debat.py:241).** `CLAUDE_CODE_OAUTH_TOKEN` wordt niet uit processen, Keychain of bestanden gehaald, maar gaat via de geërfde omgeving ook mee naar Codex en `agentapi`. Geef ieder kindproces alleen de omgevingsvariabelen die het nodig heeft. `_antigravity_omgeving` leest uitsluitend twee omgevingsvariabelen; `language_server.log` heeft alleen een ongebruikte padconstante.

4. **Middel — [debat.py:198](/Users/mehdichegini/dev/globaal-ai-debat/debat.py:198), [debat.py:445](/Users/mehdichegini/dev/globaal-ai-debat/debat.py:445).** `-g flash_lite` wordt met de standaard `-G high` als Flash high uitgevoerd. Bij de `agentapi`-terugval onderscheiden de tiers ook niet alle denkniveaus. Weiger combinaties die niet exact uitvoerbaar zijn, of stuur een aantoonbaar juiste keuze door.

5. **Middel — [debat.py:341](/Users/mehdichegini/dev/globaal-ai-debat/debat.py:341).** Zonder `GEMINI_BEWAAR_SESSIE` probeert de code op te ruimen, maar een mislukte serververwijdering wordt stil genegeerd. Maak zo’n mislukking zichtbaar en test de rechtstreekse opruimroute.

6. **Middel — [debat.py:376](/Users/mehdichegini/dev/globaal-ai-debat/debat.py:376).** `-T` wordt aan elke beurt doorgegeven, maar bij Gemini begint de wachttijd pas ná het starten en verzenden; één beurt kan dus langer duren. Gebruik één deadline vanaf het begin van de beurt.

7. **Laag — [overleg.sh:43](/Users/mehdichegini/dev/globaal-ai-debat/overleg.sh:43), [overleg.sh:79](/Users/mehdichegini/dev/globaal-ai-debat/overleg.sh:79).** De shell wist een geërfde `CLAUDE_MODEL` en eist `agentapi`, ook wanneer de rechtstreekse serverroute die niet gebruikt. Bewaar de omgevingswaarde en controleer `agentapi` alleen voor de terugvalroute.

Codex en Claude krijgen hun gekozen vlaggen; onbekende waarden falen pas bij hun CLI. Gemini weigert onbekende waarden vooraf.  
Gedaan: alleen gelezen; niets gewijzigd of verstuurd.  
Nagekeken: diff, aanroeppaden, tests en CI-configuratie; de testreeks niet opnieuw gedraaid.  
Openstaand: rechtstreekse Antigravity-aanroep en opruiming werkelijk testen; de volledige stubronde wordt op Windows overgeslagen.