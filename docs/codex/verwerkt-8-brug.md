# Verwerking ronde 8 - overleg-brug (17-10-2026)

Beslissing Mehdi 17-10-2026: brug bouwen zodat Claude zelf overleggen kan starten; de sleutel blijft in Antigravity.
Codex bouwde brug.py, brug.sh en test_brug.py.

Nagekeken door Claude:
- brug.sh, valideer_opdracht, _draai, verwerk en geheimen_weg gelezen: witte lijst op velden en opties, paden onder
  $HOME, geen shell (argumentlijst, opdracht via stdin), procesgroep stoppen bij tijdslimiet, sleutelwaarden
  uit log en status gefilterd.
- 114 tests OK (2 skipped), git diff --check en bash -n brug.sh groen.
- Rookproef met nepsleutel en stub-overleg: indienen --wacht gaf klaar/exit 0; de stub kreeg adres en sleutel;
  de door de stub afgedrukte sleutel staat in de log als [afgeschermd]; de nepsleutel staat nergens op schijf.
  SIGHUP (venster sluiten) stopt de luisteraar; de hartslag verloopt dan vanzelf (pid-controle + 60 s).
- Kanttekening: kill -INT op een achtergrondproces werkt niet (shell negeert SIGINT voor achtergrondjobs);
  in de Antigravity-terminal draait de brug op de voorgrond, daar werkt Ctrl+C.
