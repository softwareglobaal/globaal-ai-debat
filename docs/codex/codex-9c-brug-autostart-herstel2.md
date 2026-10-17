**Klaar met kanttekening:** O9c is hersteld in de worktree en niet gecommit.

1. De luisteraar rondt een gestopte taak af met log en eindstatus 130. De sidecar pauzeert de oude luisteraar, controleert opnieuw en hervat hem altijd. De signaaltest en twee wachtrijtests zijn groen.
2. Herstel bewaart een al geschreven eindstatus. Een wachtende indiener sluit een verweesde taak zelf af zodra het slot vrij is. Beide gerichte tests zijn groen.
3. Heartbeat en Gemini-RPC weigeren ongeldige adressen zonder verzoek en gebruiken geen proxy of omleiding. De weigeringstests zijn groen; de twee nieuwe netwerkproeven kon deze sandbox niet draaien.
4. Een opgeruimd proces krijgt geen groepssignaal. “Nu stoppen” deelt het slot met registratie en afmelding. De procesgroep- en racetests zijn groen.

De voorgeschreven suite eindigde met **162 tests: OK, 25 overgeslagen**. Daarvan vereisen 23 een lokale HTTP-poort die de sandbox blokkeert; twee zijn alleen voor Windows. Claude moet de poorttests draaien. `bash -n` voor alle `.sh`-bestanden en `git diff --check` zijn schoon. [CLAUDE.md](/Users/mehdichegini/dev/_codex-brug-autostart/CLAUDE.md) is bijgewerkt.

Bewust anders: de signaal- en overnametests gebruiken tijdelijke nepbereikbaarheid en een tijdelijke `ps`-vervanger, zodat de races ook hier toetsbaar zijn. Het [O9c-verslag](/Users/mehdichegini/dev/_codex-brug-autostart/docs/codex/codex-9c-brug-autostart-herstel2.md) legt de resultaten vast.