"""Grendels die niet stil mogen sneuvelen. Draait zonder abonnementen en zonder netwerk.

    python -m unittest test_grendels -v
"""

import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import debat
import opdracht
import verkenner
import web


class VreemdeWebsite(unittest.TestCase):
    """Een website in je browser mag de lokale server niet kunnen aansturen."""

    def setUp(self):
        self.c = web.app.test_client()
        self.eigen = {"Host": "127.0.0.1:8099"}

    def test_vreemde_origin_geweigerd(self):
        r = self.c.post("/api/controleer", json={"tekst": "x"},
                        headers={**self.eigen, "Origin": "https://kwaadaardig.example"})
        self.assertEqual(r.status_code, 403)

    def test_tekst_zonder_json_geweigerd(self):
        # Dit is het verzoek dat een browser zonder preflight vanaf elke site mag sturen.
        r = self.c.post("/api/opdracht", data='{"onderwerp":{"repo":"/"}}',
                        headers={**self.eigen, "Content-Type": "text/plain"})
        self.assertEqual(r.status_code, 415)

    def test_formulier_geweigerd(self):
        r = self.c.post("/api/stop", data={"a": "b"}, headers=self.eigen)
        self.assertEqual(r.status_code, 415)

    def test_vreemde_host_geweigerd(self):
        # DNS-rebinding: een vreemde naam die naar 127.0.0.1 wijst.
        r = self.c.get("/api/status", headers={"Host": "kwaadaardig.example:8099"})
        self.assertEqual(r.status_code, 403)

    def test_eigen_pagina_werkt(self):
        r = self.c.post("/api/controleer", json={"tekst": "niets geheims"},
                        headers={**self.eigen, "Origin": "http://127.0.0.1:8099"})
        self.assertEqual(r.status_code, 200)
        r = self.c.get("/api/status", headers=self.eigen)
        self.assertEqual(r.status_code, 200)

    def test_pagina_stuurt_elke_post_als_json(self):
        pagina = (debat.BASIS / "pagina.html").read_text(encoding="utf-8")
        self.assertNotIn('{ method: "POST" }', pagina)

    def test_nu_stoppen_kan_proces_niet_tijdens_signaal_afmelden(self):
        proc = object()
        in_stop = threading.Event()
        laat_door = threading.Event()
        afgemeld = threading.Event()
        antwoorden = []
        with web.LOCK:
            oud_proc = web.HUIDIG["proc"]
            oud_stop = web.STAAT["stop_gevraagd"]
            web.HUIDIG["proc"] = proc
            web.STAAT["stop_gevraagd"] = False

        def trage_stop(lopend):
            self.assertIs(lopend, proc)
            in_stop.set()
            self.assertTrue(laat_door.wait(3), "stop bleef hangen")

        stopdraad = afmelddraad = None
        try:
            with mock.patch.object(debat, "stop_proces", side_effect=trage_stop):
                stopdraad = threading.Thread(target=lambda: antwoorden.append(
                    web.app.test_client().post("/api/stop", json={},
                                               headers={"Host": "127.0.0.1:8099"})))
                stopdraad.start()
                self.assertTrue(in_stop.wait(3), "stop werd niet aangeroepen")
                afmelddraad = threading.Thread(target=lambda: (
                    web.registreer_proces(None), afgemeld.set()))
                afmelddraad.start()
                self.assertFalse(afgemeld.wait(0.1), "proces werd vóór het signaal afgemeld")
                laat_door.set()
                stopdraad.join(timeout=3)
                afmelddraad.join(timeout=3)
            self.assertFalse(stopdraad.is_alive())
            self.assertFalse(afmelddraad.is_alive())
            self.assertEqual([antwoord.status_code for antwoord in antwoorden], [200])
        finally:
            laat_door.set()
            if stopdraad is not None:
                stopdraad.join(timeout=3)
            if afmelddraad is not None:
                afmelddraad.join(timeout=3)
            with web.LOCK:
                web.HUIDIG["proc"] = oud_proc
                web.STAAT["stop_gevraagd"] = oud_stop

    def test_late_registratie_stopt_onder_hetzelfde_slot(self):
        proc = object()
        with web.LOCK:
            oud_proc = web.HUIDIG["proc"]
            oud_stop = web.STAAT["stop_gevraagd"]
            web.HUIDIG["proc"] = None
            web.STAAT["stop_gevraagd"] = True
        try:
            with mock.patch.object(debat, "stop_proces",
                                   side_effect=lambda lopend: self.assertTrue(web.LOCK.locked())) as stop:
                web.registreer_proces(proc)
                stop.assert_called_once_with(proc)
        finally:
            with web.LOCK:
                web.HUIDIG["proc"] = oud_proc
                web.STAAT["stop_gevraagd"] = oud_stop


class GitignoreInBriefing(unittest.TestCase):
    """Wat in .gitignore staat, gaat niet mee naar de modellen. Op elk OS."""

    def test_genegeerde_submap_blijft_weg(self):
        with tempfile.TemporaryDirectory() as tmp:
            wortel = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
            (wortel / ".gitignore").write_text("geheim/\nlokaal.json\n", encoding="utf-8")
            (wortel / "geheim").mkdir()
            (wortel / "geheim" / "config.py").write_text("x = 1\n", encoding="utf-8")
            (wortel / "lokaal.json").write_text("{}", encoding="utf-8")
            (wortel / "src").mkdir()
            (wortel / "src" / "app.py").write_text("print(1)\n", encoding="utf-8")

            v = verkenner.verzamel(wortel.resolve())
            meegenomen = [Path(p).as_posix() for p in v["meegenomen"]]
            self.assertIn("src/app.py", meegenomen)
            self.assertNotIn("geheim/config.py", meegenomen)
            self.assertNotIn("lokaal.json", meegenomen)
            self.assertNotIn("geheim/config.py", v["materiaal"])


class Uitvoerder(unittest.TestCase):
    """De uitvoerder mag alleen in zijn worktree schrijven."""

    def _cmd(self, bash):
        gezien = {}

        def nep_draai(cmd, *a, **k):
            gezien["cmd"] = cmd
            return 0, "ok", ""

        oud, debat._draai = debat._draai, nep_draai
        oud_vind, debat.vind = debat.vind, lambda n: n
        try:
            opdracht.roep_uitvoerder("s", "p", "sonnet", 10, Path("."), bash)
        finally:
            debat._draai, debat.vind = oud, oud_vind
        return gezien["cmd"]

    def test_geen_bypass(self):
        for bash in (False, True):
            cmd = self._cmd(bash)
            self.assertNotIn("bypassPermissions", cmd)
            self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "acceptEdits")

    def test_bash_alleen_met_vinkje(self):
        self.assertNotIn("Bash", " ".join(self._cmd(False)))
        self.assertIn("Bash", self._cmd(True))


@unittest.skipIf(os.name == "nt", "procesgroepen bestaan alleen buiten Windows")
class Stoppen(unittest.TestCase):
    """Nu stoppen moet ook de kleinkinderen doden (codex is een Node-wrapper)."""

    def test_kleinkind_sterft_mee(self):
        with tempfile.TemporaryDirectory() as tmp:
            pidbestand = Path(tmp) / "kind.pid"
            script = (f"import subprocess,sys,time\n"
                      f"k=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\n"
                      f"open({str(pidbestand)!r},'w').write(str(k.pid))\n"
                      f"time.sleep(60)\n")
            gevangen = {}
            import threading
            t = threading.Thread(target=lambda: gevangen.setdefault(
                "r", self._draai_stil([sys.executable, "-c", script], gevangen)))
            t.start()
            for _ in range(100):
                if pidbestand.exists() and pidbestand.read_text() and gevangen.get("proc"):
                    break
                time.sleep(0.05)
            kind = int(pidbestand.read_text())
            debat.stop_proces(gevangen["proc"])
            t.join(10)
            for _ in range(40):
                try:
                    os.kill(kind, 0)
                except ProcessLookupError:
                    return
                time.sleep(0.05)
            os.kill(kind, 9)
            self.fail("kleinkind leeft nog na stop_proces")

    def test_opgeruimde_leider_krijgt_geen_groepssignaal(self):
        proc = subprocess.Popen([sys.executable, "-c", "pass"],
                                start_new_session=True)
        proc.wait(timeout=3)
        with mock.patch.object(debat.os, "killpg") as killpg:
            debat.stop_proces(proc)
            killpg.assert_not_called()

    @staticmethod
    def _draai_stil(cmd, gevangen):
        def registreer(p):
            if p is not None:
                gevangen["proc"] = p
        try:
            return debat._draai(cmd, "", 30, registreer)
        except Exception as e:
            return e


if __name__ == "__main__":
    unittest.main(verbosity=2)
