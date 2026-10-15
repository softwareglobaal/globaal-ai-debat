"""Rondes tussen Claude en Codex in het dashboard. Draait zonder abonnementen en zonder netwerk.

    python -m unittest test_ronde -v
"""

import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import debat
import ronde
import web


class Rondes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.oud = debat.RUNS
        debat.RUNS = Path(self.tmp.name) / "runs"

    def tearDown(self):
        debat.RUNS = self.oud
        self.tmp.cleanup()

    def board(self, naam):
        pad = debat.RUNS / naam / "board.jsonl"
        return [json.loads(r) for r in pad.read_text(encoding="utf-8").splitlines() if r.strip()]

    def test_volledige_ronde(self):
        naam = ronde.nieuw("Codex-controle: proef", "Lees x.py na.", project="/tmp/p", rapport="", sandbox="read-only")
        self.assertRegex(naam, ronde.NAAM)
        ronde.voeg_toe(ronde.run_pad(naam), "codex", "controle", "**Niet klaar.** 1. Hoog", model="gpt", duur=12)
        ronde.voeg_toe(ronde.run_pad(naam), "claude", "verwerking", "1. gelijk, hersteld in abc123")
        beurten = self.board(naam)
        self.assertEqual([b["soort"] for b in beurten], ["opdracht", "controle", "verwerking"])
        self.assertEqual([b["nr"] for b in beurten], [1, 2, 3])
        self.assertEqual(beurten[1]["duur_s"], 12.0)
        self.assertIsNone(beurten[0]["duur_s"])
        onderwerp = json.loads((debat.RUNS / naam / "onderwerp.json").read_text(encoding="utf-8"))
        self.assertEqual(onderwerp["modus"], "ronde")
        self.assertNotIn("rapport", onderwerp)  # lege velden blijven weg
        self.assertIn("VERWERKING (Claude)", (debat.RUNS / naam / "transcript.md").read_text(encoding="utf-8"))

    def test_zelfde_seconde_geeft_eigen_ronde(self):
        a = ronde.nieuw("a", "x", tijd="2026-10-15T16:00:00")
        b = ronde.nieuw("b", "y", tijd="2026-10-15T16:00:00")
        self.assertNotEqual(a, b)
        self.assertEqual(b, "20261015-160000-codex-2")

    def test_geen_pad_buiten_runs(self):
        for naam in ("../x", "20261015-160000-codex/../../etc", "/etc", "20261015-160000"):
            with self.assertRaises(ValueError):
                ronde.run_pad(naam)
        with self.assertRaises(FileNotFoundError):
            ronde.run_pad("20261015-160000-codex")

    def test_lege_of_onbekende_beurt_geweigerd(self):
        naam = ronde.nieuw("t", "x")
        pad = ronde.run_pad(naam)
        with self.assertRaises(ValueError):
            ronde.voeg_toe(pad, "codex", "controle", "   ")
        with self.assertRaises(ValueError):
            ronde.voeg_toe(pad, "codex", "verwerking", "Codex verwerkt niet")
        with self.assertRaises(ValueError):
            ronde.nieuw("t", "")
        self.assertEqual(len(self.board(naam)), 1)

    def test_symlink_geweigerd(self):
        # D02: een ronde of transcript die naar buiten runs/ wijst, mag nergens schrijven.
        echt = ronde.nieuw("t", "x")
        buiten = Path(self.tmp.name) / "buiten"
        buiten.mkdir()
        (buiten / "board.jsonl").write_text("", encoding="utf-8")
        doel = buiten / "transcript.md"
        doel.write_text("onaangeroerd", encoding="utf-8")
        try:
            os.symlink(buiten, debat.RUNS / "20261015-170000-codex", target_is_directory=True)
            (debat.RUNS / echt / "transcript.md").unlink()
            os.symlink(doel, debat.RUNS / echt / "transcript.md")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks niet toegestaan op dit systeem")
        with self.assertRaises(ValueError):
            ronde.run_pad("20261015-170000-codex")
        with self.assertRaises(ValueError):
            ronde.voeg_toe(ronde.Path(debat.RUNS / echt), "codex", "controle", "a")
        self.assertEqual(doel.read_text(encoding="utf-8"), "onaangeroerd")
        self.assertEqual(len(self.board(echt)), 1)

    def test_duur_eindig_en_niet_negatief(self):
        # D06: NaN is geen geldige JSON en breekt de pagina.
        pad = ronde.run_pad(ronde.nieuw("t", "x"))
        for slecht in ("nan", "inf", "-1", "abc", float("nan")):
            with self.assertRaises(ValueError, msg=repr(slecht)):
                ronde.voeg_toe(pad, "codex", "controle", "a", duur=slecht)
        self.assertEqual(len(self.board(pad.name)), 1)

    def test_gelijktijdige_beurten_elk_een_nummer(self):
        # D03: twee processen tegelijk op dezelfde ronde: geen dubbele nummers, niets kwijt.
        naam = ronde.nieuw("t", "x")
        code = ("import sys, debat, ronde\nfrom pathlib import Path\ndebat.RUNS = Path(sys.argv[1])\n"
                "p = ronde.run_pad(sys.argv[2])\n"
                "for i in range(15): ronde.voeg_toe(p, 'codex', 'controle', sys.argv[3] + str(i))\n")
        procs = [subprocess.Popen([sys.executable, "-c", code, str(debat.RUNS), naam, k],
                                  cwd=Path(__file__).parent) for k in "ab"]
        for p in procs:
            self.assertEqual(p.wait(timeout=120), 0)
        beurten = self.board(naam)
        self.assertEqual([b["nr"] for b in beurten], list(range(1, 32)))
        transcript = (debat.RUNS / naam / "transcript.md").read_text(encoding="utf-8")
        self.assertEqual(transcript.count("\n## "), 31)
        self.assertFalse((debat.RUNS / naam / ".slot").exists())

    def test_opdrachtregel_zoals_codex_sh(self):
        uit = io.StringIO()
        oud_in = sys.stdin
        try:
            sys.stdin = io.StringIO("opdracht")
            with redirect_stdout(uit):
                self.assertEqual(ronde.main(["--runs", str(debat.RUNS), "nieuw", "--titel", "cli"]), 0)
            naam = uit.getvalue().strip()
            sys.stdin = io.StringIO("")
            with redirect_stderr(io.StringIO()):
                self.assertEqual(ronde.main(["beurt", naam, "--kant", "codex", "--soort", "controle"]), 2)
        finally:
            sys.stdin = oud_in
        self.assertEqual(len(self.board(naam)), 1)

    def test_dashboard_toont_ronde(self):
        naam = ronde.nieuw("Codex-controle: dashboard", "x")
        oud = web.RUNS
        web.RUNS = debat.RUNS
        try:
            c = web.app.test_client()
            lijst = c.get("/api/runs", headers={"Host": "127.0.0.1:8099"}).get_json()
            self.assertEqual(lijst[0]["naam"], naam)
            self.assertEqual(lijst[0]["modus"], "ronde")
            r = c.get(f"/api/run/{naam}", headers={"Host": "127.0.0.1:8099"}).get_json()
            self.assertEqual(r["beurten"][0]["soort"], "opdracht")
        finally:
            web.RUNS = oud


class PaginaGrendel(unittest.TestCase):
    """Tekst uit runs (titels, sprekers, bestandsnamen uit een diff) komt als tekst op de pagina, nooit als HTML.
    Daarom mag innerHTML alleen een vaste tekst krijgen: geen variabele, geen ${...}, geen samenvoeging (D01, D07)."""

    VAST = re.compile(r"""\s*(['"])(?:(?!\1)[^`$\\])*\1\s*;""")

    def test_innerhtml_alleen_vaste_tekst(self):
        pagina = (Path(__file__).parent / "pagina.html").read_text(encoding="utf-8")
        treffers = list(re.finditer(r"\.innerHTML\s*=", pagina))
        self.assertTrue(treffers)
        for m in treffers:
            rest = pagina[m.end():]
            regel = pagina.count("\n", 0, m.start()) + 1
            self.assertTrue(self.VAST.match(rest), f"pagina.html:{regel}: innerHTML krijgt geen vaste tekst")

    def test_grendel_vangt_bestandsnamen_via_innerhtml(self):
        fout = 'regel.innerHTML = [stuk("toegevoegd", f.toegevoegd)].join(" ");'
        self.assertFalse(self.VAST.match(fout.split("=", 1)[1]))
        self.assertFalse(self.VAST.match(" `<b>${naam}</b>`;"))
        self.assertTrue(self.VAST.match(" '<div style=\"a;b\">Nog geen runs.</div>'; return;"))


if __name__ == "__main__":
    unittest.main()
