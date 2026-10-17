"""Rondes tussen Claude en Codex in het dashboard. Draait zonder abonnementen en zonder netwerk.

    python -m unittest test_ronde -v
"""

import io
import itertools
import json
import os
import shutil
import signal
import re
import subprocess
import sys
import tempfile
import threading
import time
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
        self.assertIn(f"Gestart: {naam}", (debat.RUNS / naam / "transcript.md").read_text(encoding="utf-8"))
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

    def test_driehoeksoverleg_codex_en_gemini(self):
        naam = ronde.nieuw("Overleg: proef", "Onderzoek x.py.", project="/tmp/p")
        pad = ronde.run_pad(naam)
        ronde.voeg_toe(pad, "codex", "overleg", "1. Codex eerste blik", model="gpt-6-sol", duur=10)
        ronde.voeg_toe(pad, "gemini", "overleg", "1. Gemini vult aan", model="gemini-pro", duur=8)
        ronde.voeg_toe(pad, "codex", "controle", "**Klaar met kanttekeningen.** Gezamenlijk besluit", model="gpt-6-sol", duur=9)
        ronde.voeg_toe(pad, "claude", "verwerking", "Uitgevoerd zoals besproken")
        beurten = self.board(naam)
        self.assertEqual([b["kant"] for b in beurten], ["claude", "codex", "gemini", "codex", "claude"])
        self.assertEqual([b["soort"] for b in beurten], ["opdracht", "overleg", "overleg", "controle", "verwerking"])

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

    KOP = ("import sys, time, debat, ronde\nfrom pathlib import Path\ndebat.RUNS = Path(sys.argv[1])\n"
           "p = ronde.run_pad(sys.argv[2])\n")

    def proces(self, code, *args):
        return subprocess.Popen([sys.executable, "-c", self.KOP + code, str(debat.RUNS), *args],
                                cwd=Path(__file__).parent)

    def wacht_op(self, pad, s=20):
        einde = time.monotonic() + s
        while not pad.exists():
            self.assertLess(time.monotonic(), einde, f"{pad} kwam er niet")
            time.sleep(0.02)

    def met_antwoord(self):
        naam = ronde.nieuw("t", "x")
        ronde.voeg_toe(ronde.run_pad(naam), "codex", "controle", "antwoord")
        return naam

    def test_gelijktijdige_beurten_elk_een_nummer(self):
        # D03: twee processen tegelijk op dezelfde ronde: geen dubbele nummers, niets kwijt.
        naam = self.met_antwoord()
        procs = [self.proces("for i in range(15): ronde.voeg_toe(p, 'claude', 'verwerking', sys.argv[3] + str(i))\n",
                             naam, k) for k in "ab"]
        for p in procs:
            self.assertEqual(p.wait(timeout=120), 0)
        self.assertEqual([b["nr"] for b in self.board(naam)], list(range(1, 33)))
        transcript = (debat.RUNS / naam / "transcript.md").read_text(encoding="utf-8")
        self.assertEqual(transcript.count("\n## "), 32)

    def test_trage_schrijver_houdt_slot(self):
        # D03, D08, D16: een schrijver die tussen lezen en schrijven blijft hangen, houdt het slot; een tweede
        # schrijver wacht. Geen vaste slaapduur: de houder blijft binnen tot de test hem loslaat (barrière), en
        # de tweede schrijver moet op dat moment aantoonbaar nog wachten.
        naam = self.met_antwoord()
        binnen = Path(self.tmp.name) / "binnen"
        los = Path(self.tmp.name) / "los"
        houder = self.proces(
            "def haak():\n    Path(sys.argv[3]).touch()\n    einde = time.monotonic() + 30\n"
            "    while not Path(sys.argv[4]).exists() and time.monotonic() < einde: time.sleep(0.01)\n"
            "ronde._NA_LEZEN = haak\nronde.voeg_toe(p, 'claude', 'verwerking', 'traag')\n",
            naam, str(binnen), str(los))
        self.wacht_op(binnen)
        geweigerd = threading.Event()
        ronde._NA_MISLUKTE_POGING = geweigerd.set
        self.addCleanup(setattr, ronde, "_NA_MISLUKTE_POGING", None)
        tweede = threading.Thread(target=ronde.voeg_toe,
                                  args=(ronde.run_pad(naam), "claude", "verwerking", "snel"))
        tweede.start()
        wachtte = geweigerd.wait(20)  # D22: het slot moet de tweede schrijver echt geweigerd hebben
        los.touch()
        tweede.join(30)
        self.assertEqual(houder.wait(timeout=30), 0)
        self.assertTrue(wachtte, "de tweede schrijver wachtte niet op het slot")
        beurten = self.board(naam)
        self.assertEqual([b["nr"] for b in beurten], [1, 2, 3, 4])
        self.assertEqual([b["tekst"] for b in beurten[2:]], ["traag", "snel"])

    def test_onderbroken_aanmaken_laat_geen_halve_ronde(self):
        # D13: een signaal op elk moment van het aanmaken laat ofwel niets zichtbaars achter, ofwel een volledige
        # ronde met de opdracht als eerste beurt. Staat er een naam in het naambestand, dan klopt die ronde.
        # Windows kent geen SIGINT voor een subproces; terminate() is daar een harde stop zonder opruimen.
        stops = [signal.SIGINT, signal.SIGKILL] if os.name == "posix" else ["terminate"]
        for stap, stop in itertools.product(ronde.STAPPEN_NIEUW, stops):
            with self.subTest(stap=stap, stop=str(stop)):
                for d in list(debat.RUNS.glob("*")) if debat.RUNS.exists() else []:
                    shutil.rmtree(d)
                teken = Path(self.tmp.name) / f"stap-{stap}-{stop}"
                naambestand = Path(self.tmp.name) / f"naam-{stap}-{stop}"
                p = subprocess.Popen(
                    [sys.executable, "-c",
                     "import sys, time, debat, ronde\nfrom pathlib import Path\ndebat.RUNS = Path(sys.argv[1])\n"
                     "def haak(s):\n    if s == sys.argv[2]:\n        Path(sys.argv[3]).touch(); time.sleep(30)\n"
                     "ronde._NA_STAP = haak\nronde.nieuw('t', 'opdracht', naambestand=sys.argv[4])\n",
                     str(debat.RUNS), stap, str(teken), str(naambestand)], cwd=Path(__file__).parent)
                self.wacht_op(teken)
                if stop == "terminate":
                    p.terminate()
                else:
                    p.send_signal(stop)
                p.wait(timeout=10)
                zichtbaar = [d for d in debat.RUNS.iterdir() if (d / "board.jsonl").exists()]
                for d in zichtbaar:
                    self.assertIn(f"Gestart: {d.name}", (d / "transcript.md").read_text(encoding="utf-8"))
                    beurten = [json.loads(r) for r in (d / "board.jsonl").read_text(encoding="utf-8").splitlines()
                               if r.strip()]
                    self.assertTrue(beurten and beurten[0]["soort"] == "opdracht", f"halve ronde {d.name}")
                if naambestand.exists():
                    naam = naambestand.read_text(encoding="utf-8").strip()
                    if (debat.RUNS / naam / "board.jsonl").exists():
                        self.assertEqual(self.board(naam)[0]["soort"], "opdracht")
                    else:
                        # De val van codex.sh kent de naam, maar de ronde is niet zichtbaar: een FOUT maakt niets aan.
                        with self.assertRaises(FileNotFoundError):
                            ronde.run_pad(naam)

    def test_naam_alleen_van_eigen_ronde(self):
        # D17: tien aanroepen in dezelfde seconde: elk naambestand noemt de eigen ronde, met de eigen opdracht.
        procs = []
        for k in range(10):
            procs.append(subprocess.Popen(
                [sys.executable, "-c",
                 "import sys, debat, ronde\nfrom pathlib import Path\ndebat.RUNS = Path(sys.argv[1])\n"
                 "ronde.nieuw('t', 'opdracht ' + sys.argv[2], tijd='2026-10-15T19:00:00', naambestand=sys.argv[3])\n",
                 str(debat.RUNS), str(k), str(Path(self.tmp.name) / f"naam-{k}")], cwd=Path(__file__).parent))
        for p in procs:
            self.assertEqual(p.wait(timeout=60), 0)
        namen = set()
        for k in range(10):
            naam = (Path(self.tmp.name) / f"naam-{k}").read_text(encoding="utf-8").strip()
            namen.add(naam)
            self.assertEqual(self.board(naam)[0]["tekst"], f"opdracht {k}")
        self.assertEqual(len(namen), 10)

    def test_lege_map_van_ander_proces_wordt_niet_vervangen(self):
        # D17: een map met dezelfde naam, ook leeg, is van een ander; nieuw() kiest een andere naam.
        debat.RUNS.mkdir(parents=True, exist_ok=True)
        (debat.RUNS / "20261015-190000-codex").mkdir()
        naam = ronde.nieuw("t", "x", tijd="2026-10-15T19:00:00")
        self.assertEqual(naam, "20261015-190000-codex-2")
        self.assertEqual(list((debat.RUNS / "20261015-190000-codex").iterdir()), [])

    def test_resten_zichtbaar_en_op_te_ruimen(self):
        # D20: een harde stop tijdens nieuw() laat een rondemap zonder board.jsonl achter; resten() toont die,
        # --weg ruimt alleen die op, nooit een volledige ronde of iets jongs.
        heel = ronde.nieuw("t", "x")
        rest = debat.RUNS / "20261015-010000-codex"
        rest.mkdir()
        (rest / "onderwerp.json").write_text("{}", encoding="utf-8")
        oud = debat.RUNS / ".nieuw-abc"
        oud.mkdir()
        jong = debat.RUNS / "20261015-020000-codex"
        jong.mkdir()
        for d in (rest, oud):
            os.utime(d, (time.time() - 3600, time.time() - 3600))
        self.assertEqual(ronde.resten(), sorted([rest, oud]))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(ronde.main(["--runs", str(debat.RUNS), "resten", "--weg"]), 0)
        self.assertFalse(rest.exists() or oud.exists())
        self.assertTrue(jong.exists() and (debat.RUNS / heel / "board.jsonl").exists())

    def test_slot_vervangen_tussen_controle_en_openen(self):
        # D21: een ander proces vervangt .slot door een symlink net na de controle. De volledige slotroute moet
        # weigeren: op POSIX door O_NOFOLLOW, op Windows door de identiteitscontrole; nooit een slot of schrijven
        # op het bestand erachter.
        naam = self.met_antwoord()
        slot = debat.RUNS / naam / ".slot"
        buiten = Path(self.tmp.name) / "buiten-slot"
        buiten.write_text("onaangeroerd", encoding="utf-8")
        echt_open = os.open
        gewisseld = []

        def open_met_wissel(pad, *args, **kw):
            if str(pad) == str(slot) and not gewisseld:
                gewisseld.append(True)
                slot.unlink()
                os.symlink(buiten, slot)
            return echt_open(pad, *args, **kw)

        try:
            os.symlink(buiten, Path(self.tmp.name) / "proef-symlink")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks niet toegestaan op dit systeem")
        ronde.os.open = open_met_wissel
        try:
            with self.assertRaises(ValueError):
                ronde.voeg_toe(ronde.run_pad(naam), "claude", "verwerking", "x")
        finally:
            ronde.os.open = echt_open
        self.assertTrue(gewisseld)
        self.assertEqual(buiten.read_text(encoding="utf-8"), "onaangeroerd")
        self.assertEqual(len(self.board(naam)), 2)

    def test_uitkomst_nooit_als_eerste_beurt(self):
        # D13: ook als een ronde ooit zonder opdracht zou bestaan, wordt FOUT nooit de eerste beurt.
        debat.RUNS.mkdir(parents=True, exist_ok=True)
        leeg = debat.RUNS / "20261015-180000-codex"
        leeg.mkdir()
        (leeg / "board.jsonl").write_text("", encoding="utf-8")
        (leeg / "onderwerp.json").write_text('{"vraag": "t"}', encoding="utf-8")
        with self.assertRaises(ValueError):
            ronde.voeg_toe(ronde.run_pad(leeg.name), "codex", "fout", "onderbroken")

    def test_geopend_slot_moet_het_bestand_zelf_zijn(self):
        # D15: op Windows bestaat O_NOFOLLOW niet. Wat er ook geopend werd, het moet het gewone bestand .slot zelf
        # zijn, geen doel achter een symlink.
        naam = self.met_antwoord()
        slot = debat.RUNS / naam / ".slot"
        buiten = Path(self.tmp.name) / "buiten-slot"
        buiten.write_text("", encoding="utf-8")
        slot.unlink()
        try:
            os.symlink(buiten, slot)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks niet toegestaan op dit systeem")
        fd = os.open(buiten, os.O_RDWR)
        try:
            with self.assertRaises(ValueError):
                ronde._controleer_geopend(fd, slot)
        finally:
            os.close(fd)

    def test_slot_van_gecrasht_proces_komt_vrij(self):
        # D08: geen verlooptijd nodig; het besturingssysteem geeft het slot vrij als de houder sterft.
        naam = self.met_antwoord()
        teken = Path(self.tmp.name) / "vast"
        houder = self.proces("import os\nwith ronde._slot(p):\n    Path(sys.argv[3]).touch()\n    time.sleep(1)\n"
                             "    os._exit(9)\n", naam, str(teken))
        self.wacht_op(teken)
        self.assertEqual(houder.wait(timeout=30), 9)
        begin = time.monotonic()
        ronde.voeg_toe(ronde.run_pad(naam), "claude", "verwerking", "na de crash")
        self.assertLess(time.monotonic() - begin, 2)

    def test_slot_van_levende_houder_wordt_niet_afgepakt(self):
        naam = self.met_antwoord()
        teken = Path(self.tmp.name) / "vast"
        houder = self.proces("with ronde._slot(p):\n    Path(sys.argv[3]).touch()\n    time.sleep(3)\n",
                             naam, str(teken))
        self.wacht_op(teken)
        oud = ronde.SLOT_WACHT_S
        ronde.SLOT_WACHT_S = 0.5
        try:
            with self.assertRaises(TimeoutError):
                ronde.voeg_toe(ronde.run_pad(naam), "claude", "verwerking", "te vroeg")
        finally:
            ronde.SLOT_WACHT_S = oud
        self.assertEqual(houder.wait(timeout=30), 0)
        self.assertEqual(len(self.board(naam)), 2)

    def test_vreemd_slot_geweigerd_zonder_te_hangen(self):
        # D09: een slotmap (oude versie) of een symlink als slot: meteen een fout, geen eindeloze lus.
        naam = self.met_antwoord()
        slot = debat.RUNS / naam / ".slot"
        slot.unlink()  # het gewone slotbestand van de vorige beurt
        (slot / "vol").mkdir(parents=True)
        os.utime(slot, (0, 0))
        begin = time.monotonic()
        with self.assertRaises(ValueError):
            ronde.voeg_toe(ronde.run_pad(naam), "claude", "verwerking", "x")
        self.assertLess(time.monotonic() - begin, 2)
        (slot / "vol").rmdir()
        slot.rmdir()
        try:
            os.symlink(Path(self.tmp.name) / "elders", slot)
        except (OSError, NotImplementedError):
            return
        with self.assertRaises(ValueError):
            ronde.voeg_toe(ronde.run_pad(naam), "claude", "verwerking", "x")
        self.assertFalse((Path(self.tmp.name) / "elders").exists())

    def test_een_uitkomst_per_ronde(self):
        # D11: een tweede CONTROLE of FOUT wordt geweigerd; een verwerking pas na een uitkomst.
        pad = ronde.run_pad(ronde.nieuw("t", "x"))
        with self.assertRaises(ValueError):
            ronde.voeg_toe(pad, "claude", "verwerking", "te vroeg")
        ronde.voeg_toe(pad, "codex", "controle", "antwoord")
        for soort in ("controle", "fout"):
            with self.assertRaises(ValueError):
                ronde.voeg_toe(pad, "codex", soort, "nog een")
        ronde.voeg_toe(pad, "claude", "verwerking", "verwerkt")
        self.assertEqual([b["soort"] for b in self.board(pad.name)], ["opdracht", "controle", "verwerking"])

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


VAST = re.compile(r"""\.innerHTML\s*=(?!=)\s*(['"])(?:(?!\1)[^`$\\])*\1\s*;""")
VERBODEN = ("outerHTML", "insertAdjacentHTML", "document.write", "createContextualFragment", "DOMParser",
            "srcdoc", "parseHTMLUnsafe", "setHTMLUnsafe")


def html_fouten(tekst: str) -> list:
    """Alle plekken waar HTML uit een variabele de pagina in kan: innerHTML met iets anders dan een vaste tekst
    (ook +=), en elke andere manier om HTML in te voegen."""
    fouten = []
    for m in re.finditer(r"innerHTML", tekst):
        if not VAST.match(tekst, m.start() - 1):
            fouten.append(f"regel {tekst.count(chr(10), 0, m.start()) + 1}: innerHTML zonder vaste tekst")
    for woord in VERBODEN:
        if woord in tekst:
            fouten.append(f"{woord} is niet toegestaan")
    return fouten


class PaginaGrendel(unittest.TestCase):
    """Tekst uit runs (titels, sprekers, bestandsnamen uit een diff, antwoorden) komt als tekst op de pagina, nooit
    als HTML. innerHTML mag alleen een vaste tekst krijgen; andere HTML-invoegingen zijn verboden (D01, D07, D12)."""

    def test_pagina_heeft_geen_html_uit_variabelen(self):
        pagina = (Path(__file__).parent / "pagina.html").read_text(encoding="utf-8")
        self.assertIn("innerHTML", pagina)
        self.assertEqual(html_fouten(pagina), [])

    def test_grendel_vangt_elke_omweg(self):
        for fout in ('regel.innerHTML = [stuk("toegevoegd", f.toegevoegd)].join(" ");',
                     'regel.innerHTML += f.toegevoegd.join(", ");',
                     "el.innerHTML = `<b>${naam}</b>`;",
                     "el.innerHTML = '<b>' + naam + '</b>';",
                     "el.innerHTML\n  = naam;",
                     "el.outerHTML = naam;",
                     'el.insertAdjacentHTML("beforeend", naam);',
                     "document.write(naam);"):
            self.assertTrue(html_fouten(fout), fout)
        self.assertEqual(html_fouten("""x.innerHTML = '<div style="a;b">Nog geen runs.</div>'; return;"""), [])
        self.assertEqual(html_fouten('x.innerHTML = "";'), [])


if __name__ == "__main__":
    unittest.main()
