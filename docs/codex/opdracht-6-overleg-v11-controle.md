# Opdracht O2 - controle overleg v1.1 van Antigravity (alleen lezen)

Repo `~/dev/globaal-ai-debat`, tak main op 82eda0e. Antigravity maakte vandaag (11:37-11:56) een ongecommitte v1.1
van het driehoeksoverleg: `git diff` raakt controleer_modellen.py, debat.py, modellen.standaard.json, opdracht.py,
overleg.py, overleg.sh, pagina.html, ronde.py, test_overleg.py, web.py. Claude verbeterde daarna alleen twee
meldingen ("open de Antigravity-app" weg). De volledige testreeks is groen (95 OK, 2 skipped). Beoordeel of dit
zo gecommit kan worden. Niets wijzigen.

Let vooral op:
1. **Sleutels.** Wordt er nergens een CSRF-token, OAuth-token of andere aanmeldgegeven uit processen (ps), logs,
   Keychain of bestanden gehaald? `_antigravity_omgeving` hoort alleen de omgeving van de Antigravity-terminal te
   lezen. Wat doet de code met `CLAUDE_CODE_OAUTH_TOKEN` en met `~/Library/Logs/Antigravity/language_server.log`?
   Kan een sleutel in runs/, rapport, dashboard, foutmelding of log terechtkomen (bv. via headers of URL in een
   exception)?
2. **Keuzes.** Komen model en denkniveau echt aan bij Codex (-m/-e), Gemini (-g/-G) en Claude (-c/-E,
   --met-claude)? Wat gebeurt er bij een onbekend model of niveau?
3. **Opruimen.** Worden Gemini-sessies opgeruimd tenzij GEMINI_BEWAAR_SESSIE gezet is? Geldt -T voor elke beurt?
4. **CI.** Breekt iets op Linux of Windows? Zijn de nieuwe paden getest?

Antwoordvorm: eerst één zin "committen: ja / ja na herstel / nee". Dan per bevinding: ernst, `bestand:regel`, wat
er mis kan gaan, kleinste herstel. Geen bevindingen verzinnen; wat je niet kon nakijken, zeg je.
