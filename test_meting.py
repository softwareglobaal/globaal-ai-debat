"""Meting en vonnis: tests door de app, nulmeting, resultaat, standpunt en vonnis. Draait zonder
abonnementen en zonder netwerk; de modellen zijn nagebootst.

    python -m unittest test_meting -v
"""

import ctypes
import json
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

EIGEN = {"Host": "127.0.0.1:8099"}
OPDRACHT = "Laat gemiddelde() 0 teruggeven voor een lege lijst."
FOUT = "def gemiddelde(g):\n    return sum(g) / len(g)\n"
GOED = "def gemiddelde(g):\n    return sum(g) / len(g) if g else 0\n"
TEST = ("from reken import gemiddelde\nopen('bijproduct.txt', 'w').write('x')\n"
        "assert gemiddelde([2, 4]) == 3\nassert gemiddelde([]) == 0, 'lege lijst moet 0 geven'\n"
        "print('alle tests geslaagd')\n")


def git(map_, *args):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=map_,
                   check=True, capture_output=True)


def maak_repo(wortel: Path) -> Path:
    repo = wortel / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "reken.py").write_text(FOUT, encoding="utf-8")
    (repo / "test_reken.py").write_text(TEST, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "start")
    return repo


class Werkplaats(unittest.TestCase):
    """Een tijdelijke repo, runs- en werkplekmap per test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.repo = maak_repo(tmp)
        self.oud = (debat.RUNS, web.RUNS, opdracht.WERKPLEK)
        debat.RUNS = web.RUNS = tmp / "runs"
        opdracht.WERKPLEK = tmp / "werkplek"
        self.cmd = f'"{sys.executable}" test_reken.py'

    def tearDown(self):
        # Eerst de tijdelijke werkplek opruimen, dan pas de echte paden terugzetten.
        for w in (opdracht.WERKPLEK.iterdir() if opdracht.WERKPLEK.is_dir() else []):
            subprocess.run(["git", "worktree", "remove", "--force", str(w)], cwd=self.repo,
                           capture_output=True)
        debat.RUNS, web.RUNS, opdracht.WERKPLEK = self.oud
        self._tmp.cleanup()

    def script(self, naam, inhoud):
        """Een hulpscript buiten de repo, aan te roepen als testcommando."""
        pad = Path(self._tmp.name) / naam
        pad.write_text(inhoud, encoding="utf-8")
        return f'"{sys.executable}" "{pad}"'


class Standpunt(unittest.TestCase):
    def test_laatste_regel_telt(self):
        self.assertEqual(debat.splits_standpunt("A.\nB.\n\nSTANDPUNT: BIJGESTELD\n"),
                         ("A.\nB.", "BIJGESTELD"))
        self.assertEqual(debat.splits_standpunt("Tekst\n**STANDPUNT:** eens")[1], "EENS")
        self.assertIsNone(debat.splits_standpunt("STANDPUNT: EENS middenin\nslot")[1])
        self.assertEqual(debat.splits_standpunt("Geen regel"), ("Geen regel", None))

    def test_beide_eens_telt_moderator_niet(self):
        self.assertTrue(debat.beide_eens([{"kant": "claude", "standpunt": "EENS"}, {"kant": "mens"},
                                          {"kant": "codex", "standpunt": "EENS"}]))
        self.assertFalse(debat.beide_eens([{"kant": "claude", "standpunt": "EENS"},
                                           {"kant": "codex", "standpunt": "HANDHAAF"}]))
        self.assertFalse(debat.beide_eens([{"kant": "claude", "standpunt": "EENS"}]))


class Vonnis(unittest.TestCase):
    VELDEN = ('"besluit": "a", "doorslaggevend_argument": "b", "eens_over": "kosten", '
              '"open_punten": [], "volgende_stap": "c"')

    def test_json_uit_codeblok(self):
        v = debat.lees_vonnis('```json\n{"winnaar": "b", ' + self.VELDEN + '}\n```')
        self.assertEqual(v["winnaar"], "B")
        self.assertEqual(v["eens_over"], ["kosten"])

    def test_mislukt_zichtbaar(self):
        for tekst in ("geen json", '{"besluit": "x"}'):
            v = debat.lees_vonnis(tekst)
            self.assertIn("fout", v)
            self.assertIn("ruw", v)

    def test_winnaar(self):
        self.assertEqual(debat.lees_vonnis('{"winnaar": "gelijk", ' + self.VELDEN + '}')["winnaar"],
                         "GELIJK")
        self.assertEqual(debat.lees_vonnis('{"winnaar": "Kant A", ' + self.VELDEN + '}')["winnaar"], "A")
        # Een onbekende winnaar wordt niet stil GELIJK maar een zichtbare fout.
        self.assertIn("fout", debat.lees_vonnis('{"winnaar": "remise", ' + self.VELDEN + '}'))

    def test_lijsten_worden_tekst(self):
        v = debat.lees_vonnis('{"besluit": "a", "winnaar": "A", "doorslaggevend_argument": "b", '
                              '"eens_over": null, "open_punten": [{"punt": "kosten"}, null], '
                              '"volgende_stap": "c"}')
        self.assertEqual(v["eens_over"], [])
        self.assertEqual(v["open_punten"], ['{"punt": "kosten"}'])
        with tempfile.TemporaryDirectory() as tmp:
            o = {"vraag": "V", "claude": {"naam": "CL"}, "codex": {"naam": "CX"}}
            v.update(rechter="sonnet", winnaar_naam="CL")
            debat.schrijf_vonnis(Path(tmp), o, [], v)  # brak eerder op een object in de lijst
            self.assertIn("kosten", (Path(tmp) / "transcript.md").read_text(encoding="utf-8"))

    def test_rechter_ziet_geen_namen(self):
        o = {"vraag": "V", "context": "C", "claude": {"naam": "CLNAAM", "positie": "P1"},
             "codex": {"naam": "CXNAAM", "positie": "P2"}}
        p = debat.vonnis_prompt(o, [{"kant": "claude", "tekst": "a"}, {"kant": "mens", "tekst": "m"},
                                    {"kant": "codex", "tekst": "b"}])
        for stuk in ("[KANT A]", "[KANT B]", "[MODERATOR]"):
            self.assertIn(stuk, p)
        self.assertNotIn("CLNAAM", p)
        self.assertNotIn("CXNAAM", p)


class Omgeving(unittest.TestCase):
    """Een API-sleutel in de omgeving mag het abonnement van de Claude-kant niet overnemen."""

    def test_sleutel_weg_voor_claude(self):
        oud = os.environ.get("ANTHROPIC_API_KEY")
        os.environ["ANTHROPIC_API_KEY"] = "nep"
        try:
            env = debat.omgeving([str(Path("bin") / "claude.exe"), "-p"])
            self.assertNotIn("ANTHROPIC_API_KEY", env)
            self.assertIn("PATH", {k.upper() for k in env})
            self.assertNotIn("ANTHROPIC_API_KEY", debat.omgeving(["codex", "exec"]))
        finally:
            if oud is None:
                os.environ.pop("ANTHROPIC_API_KEY", None)
            else:
                os.environ["ANTHROPIC_API_KEY"] = oud

    def test_geheimen_alleen_naar_het_bedoelde_kindproces(self):
        nep = {"CLAUDE_CODE_OAUTH_TOKEN": "test-claude-token",
               "ANTIGRAVITY_LS_ADDRESS": "localhost:12345",
               "ANTIGRAVITY_CSRF_TOKEN": "test-antigravity-token",
               "ANTHROPIC_API_KEY": "test-api-key"}
        with mock.patch.dict(os.environ, nep):
            with mock.patch.object(debat.subprocess, "Popen") as popen:
                popen.return_value.communicate.return_value = ("", "")
                popen.return_value.returncode = 0
                kinderen = {}
                for soort in ("claude", "codex", "agentapi"):
                    debat._draai([soort], "", 1, None)
                    kinderen[soort] = popen.call_args.kwargs["env"]
        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN", kinderen["claude"])
        self.assertNotIn("ANTIGRAVITY_CSRF_TOKEN", kinderen["claude"])
        self.assertNotIn("ANTIGRAVITY_LS_ADDRESS", kinderen["claude"])
        self.assertNotIn("ANTHROPIC_API_KEY", kinderen["claude"])
        self.assertIn("ANTIGRAVITY_CSRF_TOKEN", kinderen["agentapi"])
        self.assertIn("ANTIGRAVITY_LS_ADDRESS", kinderen["agentapi"])
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", kinderen["agentapi"])
        for naam in nep:
            self.assertNotIn(naam, kinderen["codex"])

    def test_subproces_deadline_telt_opstarttijd_mee(self):
        klok = [100.0]
        wachttijden = []

        def start(*args, **kwargs):
            klok[0] += 8
            proc = mock.Mock()
            proc.returncode = 0
            proc.communicate.side_effect = lambda *a, **k: (wachttijden.append(k["timeout"]) or ("", ""))
            return proc

        with mock.patch.object(debat.time, "monotonic", side_effect=lambda: klok[0]):
            with mock.patch.object(debat.subprocess, "Popen", side_effect=start):
                debat._draai(["agentapi"], "", 10, None, deadline=110.0)
        self.assertEqual(wachttijden, [2.0])


class Briefingcontrole(unittest.TestCase):
    """De controle op wat niet naar OpenAI hoort (briefing van een projectmap)."""

    @staticmethod
    def soorten(tekst):
        return {t["soort"] for t in verkenner.controleer_briefing(tekst)}

    def test_ip_host_en_mail(self):
        self.assertTrue({"IP-adres", "hostnaam", "e-mailadres"} <= self.soorten(
            "verbinding met 10.1.2.3 en db.globaal.be faalde, mail jan@voorbeeld.nl"))

    def test_verbindingsreeksen(self):
        for reeks in ("postgres://admin:Geheim!Wachtwoord2026@db.example.com:5432/app",
                      "redis://deploy:wachtwoord@cache.intern:6379/0",
                      "redis://:Wachtwoord2026@redis:6379/0",
                      "postgres://app:Xy7/kL9+qPz2@db:5432/app",
                      "https://deploy:Ab/9xQ+zz@db.example.com/app",
                      "postgresql+psycopg2://app:geheim@db:5432/app",
                      "psql -dpostgres://admin:Geheim2026@db:5432/app"):
            self.assertIn("verbindingsreeks", self.soorten(f"fout bij {reeks} na 3 pogingen"), reeks)

    def test_gewone_url_is_geen_verbindingsreeks(self):
        self.assertNotIn("verbindingsreeks", self.soorten("zie http://host:8080/pad en mail jan@x.nl"))
        # Een poort met een pad dat '@' bevat, is geen wachtwoord.
        for url in ("http://localhost:5173/@vite/client", "https://registry.npmjs.org:443/@types/node"):
            self.assertEqual(verkenner.controleer_briefing(url), [])

    def test_aan_elkaar_hangende_adressen(self):
        treffers = verkenner.controleer_briefing("mail jan@x.nl+piet@voorbeeld.be")
        self.assertEqual(len(treffers), 1)
        self.assertNotIn("piet", treffers[0]["gemaskeerd"])

    def test_vijandige_invoer_blijft_lineair(self):
        begin = time.time()
        for stuk in ("a" * 40000, "a." * 20000, "a-" * 20000, "a+" * 20000, "a1:" * 13000):
            verkenner.controleer_briefing(stuk)
        self.assertLess(time.time() - begin, 5)

    def test_afkappen_zichtbaar(self):
        self.assertEqual(opdracht.staart("abc", 10), "abc")
        self.assertTrue(opdracht.staart("x" * 30, 10).startswith("(eerste 20 tekens"))


class TestsDoorDeApp(Werkplaats):
    def test_rood_groen_en_opruimen(self):
        werkmap, _ = opdracht.maak_worktree(self.repo)
        t0 = opdracht.draai_tests(werkmap, self.cmd, 60)
        self.assertFalse(t0["groen"])
        self.assertIn("lege lijst moet 0 geven", t0["uitvoer"])
        self.assertIn("bijproduct.txt", t0["opgeruimd"])
        self.assertFalse((werkmap / "bijproduct.txt").exists())

        (werkmap / "reken.py").write_text(GOED, encoding="utf-8")
        (werkmap / "nieuw.py").write_text("X = 1\n", encoding="utf-8")
        voor = opdracht.diff_van(werkmap)
        t1 = opdracht.draai_tests(werkmap, self.cmd, 60)
        self.assertTrue(t1["groen"])
        self.assertTrue((werkmap / "nieuw.py").exists(), "werk van de uitvoerder mag niet weg")
        na = opdracht.diff_van(werkmap)
        self.assertNotIn("bijproduct", na["diff"])
        self.assertEqual(na["toegevoegd"], voor["toegevoegd"])

    def test_timeout(self):
        werkmap, _ = opdracht.maak_worktree(self.repo)
        t = opdracht.draai_tests(werkmap, f'"{sys.executable}" -c "import time; time.sleep(30)"', 2)
        self.assertTrue(t["timeout"])
        self.assertFalse(t["groen"])
        self.assertTrue(opdracht.testuitslag(t).startswith("TIMEOUT"))

    def test_achtergrondproces_houdt_de_run_niet_vast(self):
        # De tests slagen, maar laten een proces achter dat de uitvoer openhoudt.
        werkmap, _ = opdracht.maak_worktree(self.repo)
        cmd = self.script("achtergrond.py",
                          "import subprocess, sys, tempfile\n"
                          "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(8)'],"
                          " cwd=tempfile.gettempdir())\n"
                          "print('tests ok')\n")
        t = opdracht.draai_tests(werkmap, cmd, 4)
        self.assertTrue(t["groen"], t)
        self.assertFalse(t["timeout"])
        self.assertLess(t["duur_s"], 4)
        self.assertIn("tests ok", t["uitvoer"])

    def test_achtergrondproces_met_open_bestand_in_de_worktree(self):
        # Een testserver die een log in de worktree openhoudt: mag de opruiming niet breken
        # en mag na afloop niet blijven draaien (op Windows via het Job Object).
        werkmap, _ = opdracht.maak_worktree(self.repo)
        cmd = self.script("server.py",
                          "import os, subprocess, sys\nos.makedirs('tmp/server')\n"
                          "subprocess.Popen([sys.executable, '-c', \"f = open('tmp/server/server.log', 'w');"
                          " import time; time.sleep(10)\"])\n"
                          "import time; time.sleep(1)\nprint('tests ok')\n")
        begin = time.time()
        t = opdracht.draai_tests(werkmap, cmd, 30)
        self.assertTrue(t["groen"], t)
        self.assertLess(time.time() - begin, 8)
        self.assertEqual(t["niet_opgeruimd"], [])
        self.assertFalse((werkmap / "tmp").exists())

    @unittest.skipUnless(os.name == "nt", "Job Objects bestaan alleen op Windows")
    def test_uitbreken_uit_de_taakgroep_mag(self):
        werkmap, _ = opdracht.maak_worktree(self.repo)
        cmd = self.script("uitbreken.py",
                          "import subprocess, sys\n"
                          "import tempfile\n"
                          "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(1)'],"
                          " creationflags=0x01000000 | 0x8, cwd=tempfile.gettempdir())\n"
                          "print('tests ok')\n")
        t = opdracht.draai_tests(werkmap, cmd, 30)
        self.assertTrue(t["groen"], t["uitvoer"])

    @unittest.skipUnless(os.name == "nt", "Job-handles bestaan alleen op Windows")
    def test_geen_handlelek_als_starten_faalt(self):
        tel = ctypes.windll.kernel32.GetProcessHandleCount
        tel.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        zelf = ctypes.windll.kernel32.GetCurrentProcess()

        def handles():
            n = ctypes.c_uint32()
            tel(zelf, ctypes.byref(n))
            return n.value

        voor = handles()
        for _ in range(50):
            with self.assertRaises(OSError):
                opdracht.draai_tests(Path(self._tmp.name) / "bestaat-niet", self.cmd, 5)
        self.assertLess(handles() - voor, 10)

    def test_uitvoer_zonder_cr_en_paden_leesbaar(self):
        werkmap, _ = opdracht.maak_worktree(self.repo)
        cmd = self.script("cr.py", "open('rapport é.txt', 'w').write('x')\nprint('regel1')\nprint('regel2')\n")
        t = opdracht.draai_tests(werkmap, cmd, 30)
        self.assertNotIn("\r", t["uitvoer"])
        self.assertIn("regel1\nregel2", t["uitvoer"])
        self.assertIn("rapport é.txt", t["opgeruimd"])

    def test_opruimen_werkt_ook_met_een_andere_taal(self):
        werkmap, _ = opdracht.maak_worktree(self.repo)
        oud = {k: os.environ.get(k) for k in ("LANG", "LANGUAGE")}
        os.environ.update(LANG="fr_FR.UTF-8", LANGUAGE="fr")
        try:
            t = opdracht.draai_tests(werkmap, self.cmd, 30)
        finally:
            for k, v in oud.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.assertIn("bijproduct.txt", t["opgeruimd"])
        self.assertFalse((werkmap / "bijproduct.txt").exists())

    def test_gewijzigd_vastgelegd_bestand_teruggezet_en_gemeld(self):
        werkmap, _ = opdracht.maak_worktree(self.repo)
        cmd = self.script("overschrijf.py", "open('reken.py', 'w').write('kapot')\n")
        t = opdracht.draai_tests(werkmap, cmd, 30)
        self.assertIn("reken.py", t["opgeruimd"])
        self.assertEqual((werkmap / "reken.py").read_text(encoding="utf-8"), FOUT)

    def test_geneste_repo_van_de_tests_verdwijnt(self):
        werkmap, _ = opdracht.maak_worktree(self.repo)
        cmd = self.script("geneste_repo.py",
                          "import os, subprocess\nos.makedirs('tmp/fixture')\n"
                          "subprocess.run(['git', 'init', '-q', 'tmp/fixture'], check=True)\n"
                          "open('tmp/fixture/a.txt', 'w').write('x')\n")
        t = opdracht.draai_tests(werkmap, cmd, 30)
        self.assertTrue(t["groen"], t["uitvoer"])
        self.assertFalse((werkmap / "tmp").exists())
        self.assertFalse(any(r.startswith("Would skip") for r in t["opgeruimd"]))
        opdracht.diff_van(werkmap)  # faalde eerder met 'adding files failed'


class Opdrachtstroom(Werkplaats):
    """De hele opdrachtrun met nagebootste modellen: stoppen op het juiste moment, resultaat in velden."""

    def draai(self, cmd=None, oplossingen=(GOED,), zonder_tests=False):
        """oplossingen: wat de nagebootste uitvoerder per ronde in reken.py zet."""
        aanroepen = {"uitvoerder": 0, "prompts": []}

        def uitvoerder(systeem, prompt, model, timeout, werkmap, bash, registreer=None):
            aanroepen["prompts"].append(prompt)
            tekst = oplossingen[min(aanroepen["uitvoerder"], len(oplossingen) - 1)]
            aanroepen["uitvoerder"] += 1
            (Path(werkmap) / "reken.py").write_text(tekst, encoding="utf-8")
            return "reken.py aangepast."

        def geen_chatgpt(*a, **k):
            raise AssertionError("de opdrachtmodus hoort ChatGPT niet aan te roepen")

        oud = (opdracht.roep_uitvoerder, debat.roep_codex)
        opdracht.roep_uitvoerder, debat.roep_codex = uitvoerder, geen_chatgpt
        try:
            web.draai_opdracht(
                {"vraag": OPDRACHT, "opdracht": OPDRACHT, "repo": str(self.repo)},
                {"rondes": 3, "max_woorden": 100, "claude_model": "sonnet", "bash": False,
                 "testcommando": "" if zonder_tests else (cmd or self.cmd), "label": "T1",
                 "timeout": 60, "test_timeout": 60})
        finally:
            opdracht.roep_uitvoerder, debat.roep_codex = oud
        run = next(web.RUNS.iterdir())
        return json.loads((run / "resultaat.json").read_text(encoding="utf-8")), aanroepen

    def test_stopt_bij_groen(self):
        r, n = self.draai()
        self.assertEqual((r["variant"], r["tests_start"], r["tests_eind"]), ("solo", False, True))
        self.assertEqual((r["rondes_gedraaid"], r["stop_reden"]), (1, "tests groen"))
        self.assertEqual(n["uitvoerder"], 1)
        self.assertIsNone(r["fout"])
        self.assertIsNone(r["reviewer"])

    def test_rood_geeft_een_volgende_ronde_met_de_testuitvoer(self):
        # Ronde 1 laat de fout staan (alleen een commentaarregel erbij), ronde 2 herstelt.
        r, n = self.draai(oplossingen=("# poging\n" + FOUT, GOED))
        self.assertEqual((r["rondes_gedraaid"], r["tests_per_ronde"], r["stop_reden"]),
                         (2, [False, True], "tests groen"))
        self.assertIn("Dit is ronde 2", n["prompts"][1])
        self.assertIn("lege lijst moet 0 geven", n["prompts"][1])

    def test_zonder_tests_een_ronde(self):
        r, n = self.draai(zonder_tests=True)
        self.assertEqual((r["rondes_gepland"], r["rondes_gedraaid"], r["stop_reden"], n["uitvoerder"]),
                         (1, 1, "geen tests: een ronde", 1))
        self.assertEqual(web.STAAT["totaal"], 1, "de teller hoort geen rondes te beloven die niet komen")

    def test_ronde_zonder_wijziging_stopt(self):
        # Rood, en de uitvoerder schrijft elke ronde precies hetzelfde: na ronde 2 is het op.
        r, n = self.draai(oplossingen=("# poging\n" + FOUT,))
        self.assertEqual((r["rondes_gedraaid"], r["tests_per_ronde"], r["stop_reden"], n["uitvoerder"]),
                         (2, [False], "uitvoerder wijzigde niets meer", 2))
        self.assertIsNone(r["fout"])

    def test_reviewer_is_weg(self):
        for naam in ("roep_reviewer", "review_prompt", "REVIEWER", "splits_oordeel"):
            self.assertFalse(hasattr(opdracht, naam), naam)

    def test_nu_stoppen_tijdens_tests_is_geen_rode_test(self):
        # Na de wijziging blijven de tests lang lopen; tijdens die teststap druk jij Nu stoppen.
        cmd = self.script("traag.py",
                          "import time\nif 'if g' in open('reken.py').read():\n    time.sleep(30)\n"
                          "raise SystemExit(1)\n")
        c = web.app.test_client()

        def stop_tijdens_tests():
            for _ in range(200):
                if web.STAAT["bezig_met"] == "TESTS (na ronde 1)" and web.HUIDIG["proc"]:
                    c.post("/api/stop", json={}, headers=EIGEN)
                    return
                time.sleep(0.05)

        stopper = threading.Thread(target=stop_tijdens_tests)
        stopper.start()
        r, _ = self.draai(cmd=cmd)
        stopper.join(15)
        self.assertEqual(r["stop_reden"], "door jou gestopt")
        self.assertFalse(r["tests_start"])
        self.assertEqual((r["tests_per_ronde"], r["tests_eind"]), ([], None))
        run = next(web.RUNS.iterdir())
        laatste = json.loads((run / "board.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual((laatste["tekst"], laatste["test"]["groen"]),
                         ("AFGEBROKEN (door jou gestopt)", None))

    def test_run_zonder_beurten_te_openen(self):
        run = web.RUNS / "20260101-000000"
        run.mkdir(parents=True)
        (run / "onderwerp.json").write_text('{"vraag": "q"}', encoding="utf-8")
        (run / "resultaat.json").write_text('{"fout": "geen worktree"}', encoding="utf-8")
        r = web.app.test_client().get(f"/api/run/{run.name}", headers=EIGEN)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["beurten"], [])

    def test_oordeel_bewaren_via_eigen_pagina(self):
        self.draai()
        run = next(web.RUNS.iterdir()).name
        c = web.app.test_client()
        r = c.post(f"/api/resultaat/{run}", json={"terecht": "1", "totaal": 2, "bruikbaar": True,
                                                  "notitie": "ok"}, headers=EIGEN)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["oordeel"], {"terecht": 1, "totaal": 2, "bruikbaar": True,
                                                   "notitie": "ok"})
        lijst = c.get("/api/resultaten", headers=EIGEN).get_json()
        self.assertEqual((lijst[0]["run"], lijst[0]["oordeel"]["totaal"]), (run, 2))
        # De grendel geldt ook hier: geen JSON of een andere website wordt geweigerd.
        self.assertEqual(c.post(f"/api/resultaat/{run}", data="{}", headers={
            **EIGEN, "Content-Type": "text/plain"}).status_code, 415)
        self.assertEqual(c.post(f"/api/resultaat/{run}", json={}, headers={
            **EIGEN, "Origin": "https://kwaadaardig.example"}).status_code, 403)
        self.assertEqual(c.post("/api/resultaat/bestaat-niet", json={}, headers=EIGEN).status_code, 404)


class Debatstroom(Werkplaats):
    """Het debat met nagebootste modellen: stoppen bij wederzijds EENS en eindigen met een vonnis."""

    VONNIS = ('{"besluit": "Doe B.", "winnaar": "B", "doorslaggevend_argument": "x", '
              '"eens_over": [], "open_punten": ["y"], "volgende_stap": "z"}')
    ONDERWERP = {"vraag": "V?", "context": "C", "claude": {"naam": "CL", "positie": "a"},
                 "codex": {"naam": "CX", "positie": "b"}}

    def debat(self, claude_beurt, codex_beurt, beurten=8):
        """claude_beurt/codex_beurt krijgen het beurtnummer van die kant en geven tekst terug."""
        teller = {"claude": 0, "codex": 0}

        def claude(systeem, prompt, model, timeout, registreer=None):
            if systeem == debat.RECHTER:
                return self.VONNIS
            teller["claude"] += 1
            return claude_beurt(teller["claude"])

        def codex(systeem, prompt, model, timeout, registreer=None):
            teller["codex"] += 1
            return codex_beurt(teller["codex"])

        oud = (debat.roep_claude, debat.roep_codex)
        debat.roep_claude, debat.roep_codex = claude, codex
        try:
            web.draai(self.ONDERWERP, {"beurten": beurten, "max_woorden": 50, "claude_model": "sonnet",
                                       "codex_model": "", "start": "claude", "timeout": 30})
        finally:
            debat.roep_claude, debat.roep_codex = oud
        run = next(web.RUNS.iterdir())
        board = [json.loads(r) for r in (run / "board.jsonl").read_text(encoding="utf-8").splitlines()]
        vonnis = json.loads((run / "vonnis.json").read_text(encoding="utf-8")) \
            if (run / "vonnis.json").exists() else None
        return board, vonnis, run

    def test_eens_stopt_en_vonnis_volgt(self):
        board, v, run = self.debat(lambda n: "Ik geef toe.\nSTANDPUNT: EENS",
                                   lambda n: "Dat klopt.\nSTANDPUNT: EENS")
        self.assertEqual(len(board), 2, "na twee keer EENS hoort het debat te stoppen")
        self.assertEqual(board[0]["tekst"], "Ik geef toe.")
        self.assertEqual(web.STAAT["stop_reden"], "beide kanten melden EENS")
        self.assertEqual((v["winnaar"], v["winnaar_naam"]), ("B", "CX"))
        self.assertIn("## Vonnis", (run / "transcript.md").read_text(encoding="utf-8"))

    def test_alleen_standpuntregel_is_een_geldige_beurt(self):
        board, v, _ = self.debat(lambda n: "Ik geef toe.\nSTANDPUNT: EENS", lambda n: "STANDPUNT: EENS")
        # De instemming blijft leesbaar voor rechter en tegenpartij, die alleen de tekst zien.
        self.assertEqual(board[1]["tekst"], debat.ALLEEN_STANDPUNT.format("EENS"))
        self.assertIn("EENS", debat.vonnis_prompt(self.ONDERWERP, board).split("[KANT B]")[1])
        self.assertEqual(web.STAAT["stop_reden"], "beide kanten melden EENS")
        self.assertIsNone(web.STAAT["fout"])
        self.assertIsNotNone(v)

    def test_fout_halverwege_krijgt_toch_een_vonnis(self):
        def codex(n):
            if n == 2:
                raise RuntimeError("codex gaf exitcode 1: limiet")
            return "Nee.\nSTANDPUNT: HANDHAAF"

        board, v, _ = self.debat(lambda n: "Ja.\nSTANDPUNT: HANDHAAF", codex)
        self.assertEqual(len(board), 3)
        self.assertIn("limiet", web.STAAT["fout"])
        self.assertEqual(v["winnaar"], "B")

    def test_nieuw_punt_van_moderator_stopt_niet_op_eens(self):
        def codex(n):
            # Terwijl ChatGPT zijn EENS-beurt schrijft, breng jij een nieuw punt in.
            if n == 1:
                with web.LOCK:
                    web.INJECTIES.append("En de kosten?")
            return "Akkoord.\nSTANDPUNT: EENS"

        board, _, _ = self.debat(lambda n: "Goed.\nSTANDPUNT: EENS", codex)
        sprekers = [b["kant"] for b in board]
        self.assertEqual(sprekers, ["claude", "codex", "mens", "claude"],
                         "het nieuwe punt hoort nog een antwoord te krijgen")
        c = web.app.test_client()
        s = c.get("/api/status", headers=EIGEN).get_json()
        self.assertEqual((s["aantal"], s["debatbeurten"]), (4, 3), "de teller telt de moderator niet")
        self.assertEqual(c.get("/api/runs", headers=EIGEN).get_json()[0]["beurten"], 3,
                         "de geschiedenis telt hetzelfde als de live teller")

    def test_stop_net_voor_registratie_gaat_niet_verloren(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        web.zet(stop_gevraagd=True)
        try:
            web.registreer_proces(proc)
            self.assertIsNotNone(proc.wait(timeout=10), "het proces had afgeschoten moeten worden")
        finally:
            web.registreer_proces(None)
            web.zet(stop_gevraagd=False)
            if proc.poll() is None:
                proc.kill()

    def test_inbreng_geweigerd_als_er_geen_debat_loopt(self):
        web.zet(actief=False)
        r = web.app.test_client().post("/api/injectie", json={"tekst": "hallo"}, headers=EIGEN)
        self.assertEqual(r.status_code, 409)


if __name__ == "__main__":
    unittest.main(verbosity=2)
