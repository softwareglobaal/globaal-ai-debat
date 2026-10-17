# Verwerking O9 - brug start vanzelf (Claude, 17-10-2026)

Beslissing: live, na drie toetsrondes en een bevestiging, eindstand GO 3-0 (Codex, Gemini, Claude).

- Gemeten: Antigravity 2.24 voert geen `.vscode/tasks.json` uit (geen extensie-host; `app.asar` zonder `tasks.json`,
  `runOptions`, `folderOpen`). Wel sidecars (`~/.gemini/config/sidecars/<id>/sidecar.json`) die de server start,
  bewaakt en herstart, en die de Antigravity-toegang erven. De brug draait daarom als sidecar `overleg-brug`.
- O9 (maken): toegangscontrole met exitcode 3, ouderbewaking, reserve, `installeer_sidecar.sh`, doorstuurtests.
- Toets 1 NO-GO 3-0: stoppen liet kinderen doordraaien, gat bij overdracht, geheimen met spaties; plus Claude: de
  bestaande luisteraar met oude code zou het slot vasthouden. Hersteld in O9b.
- Toets 2 NO-GO 3-0: stop midden in een bestandswissel, eindstatus kon verloren gaan, token niet strikt lokaal,
  `stop_proces`-race. Hersteld in O9c (laatste losse herstelronde volgens de stopregel; aantal punten daalde).
- Toets 3 NO-GO 2-0: SIGKILL na opruimen van de leider (hoog), STOP niet bevestigd (middel). Claude herstelde beide
  zelf met tests die op de oude code falen: `os.waitid(..., WNOWAIT)` en `staat_stil` met `/bin/ps`. Gemeten op deze
  Mac: `killpg` op een groep met alleen de zombie-leider geeft EPERM; nu opgevangen.
- Claude herstelde ook drie testraces: CI faalt nu op een geblokkeerde loopbackpoort in plaats van over te slaan,
  nep-servers lezen de body (anders RST en af en toe "verbinding mislukt"), nep-overleg schrijft zijn teller atomisch.
- Bevestiging GO 3-0. De twee lage restpunten (gedeeltelijke uitvoer bewaren bij een vastgehouden pijp; procesgroeptest
  zonder testserver) meteen meegenomen.
- Uitslag: 164 tests groen buiten de sandbox, meermaals herhaald, ook onder belasting.
- Open voor Mehdi: de sidecar eenmalig laten installeren door Antigravity (Claude's beveiligingslaag weigert dat zelf)
  en zo nodig aanzetten in Automations.
