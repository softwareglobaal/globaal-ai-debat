**Klaar voor Claude’s controle.** De opdracht staat in deze worktree; er is niet gecommit of gepusht.

1. Zonder Gemini-toegang stopt het overleg vóór Codex start, met exitcode 2 en de instructie voor de Terminal van Antigravity. Dat geldt ook voor `--zelftest`. Zie [overleg.py](/Users/mehdichegini/dev/_overleg-vastzetten/overleg.py:120) en [overleg.sh](/Users/mehdichegini/dev/_overleg-vastzetten/overleg.sh:58).
2. `-T/--timeout` accepteert een positief geheel getal, standaard 1200 seconden, en geldt voor beide beurten. `overleg.sh -T` geeft de waarde door. Zie [overleg.py](/Users/mehdichegini/dev/_overleg-vastzetten/overleg.py:217) en [overleg.sh](/Users/mehdichegini/dev/_overleg-vastzetten/overleg.sh:86).
3. Help en korte gebruiksinstructies staan in [overleg.sh](/Users/mehdichegini/dev/_overleg-vastzetten/overleg.sh:5) en [README.md](/Users/mehdichegini/dev/_overleg-vastzetten/README.md:109).
4. [test_overleg.py](/Users/mehdichegini/dev/_overleg-vastzetten/test_overleg.py:1) test de vroege stop, timeout en een volledige ronde met stubs in tijdelijke mappen.
5. CI draait de nieuwe test mee via [grendels.yml](/Users/mehdichegini/dev/_overleg-vastzetten/.github/workflows/grendels.yml:15).
6. De opgegeven volledige reeks: **93 tests, OK, 2 overgeslagen**. `git diff --check` en `bash -n overleg.sh` zijn ook groen.

Bewust niet uitgevoerd: echte agentoproepen en een echte `--zelftest`. Windows is lokaal niet getest; de bash-tests worden daar overgeslagen.