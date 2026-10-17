"""Overleg-brug met alleen tijdelijke mappen en een nep-overlegscript."""

import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import brug


HIER = Path(__file__).parent
STUB = """#!{python}
import json
import os
import subprocess
import sys
import time
from pathlib import Path

args = sys.argv[1:]
opdracht = sys.stdin.read()
if (not os.environ.get('ANTIGRAVITY_LS_ADDRESS')
        or not os.environ.get('ANTIGRAVITY_CSRF_TOKEN')):
    sys.exit(19)
if os.environ.get('STUB_MODE') == 'sleep':
    subprocess.Popen([sys.executable, '-c',
                      'import time; from pathlib import Path; time.sleep(1.2); Path(' +
                      repr(os.environ['STUB_KIND_MARKER']) + ').write_text("leeft")'])
    time.sleep(30)
if os.environ.get('STUB_MODE') == 'fout':
    print('bewuste fout')
    sys.exit(7)
rapport = Path(args[args.index('-o') + 1])
rapport.parent.mkdir(parents=True, exist_ok=True)
rapport.write_text('# Stubrapport\\n', encoding='utf-8')
Path(os.environ['STUB_RESULTAAT']).write_text(json.dumps({
    'args': args, 'opdracht': opdracht, 'cwd': os.getcwd(),
    'heeft_adres': bool(os.environ.get('ANTIGRAVITY_LS_ADDRESS')),
    'heeft_token': bool(os.environ.get('ANTIGRAVITY_CSRF_TOKEN')),
}), encoding='utf-8')
print(os.environ['ANTIGRAVITY_CSRF_TOKEN'])
print(os.environ['ANTIGRAVITY_LS_ADDRESS'], file=sys.stderr)
"""


class BrugTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "thuis"
        self.home.mkdir()
        self.basis = self.home / "brug"
        self.werk = self.home / "werk"
        self.werk.mkdir()
        self.rapport = self.home / "rapport" / "uit.md"
        self.resultaat = self.root / "stub-resultaat.json"
        self.marker = self.root / "kind-overleefde"
        self.token = "HERKENBARE-NEPSLEUTEL-2026-TEST"
        self.adres = "HERKENBAAR-NEPADRES-2026-TEST"
        self.env = {**os.environ, "HOME": str(self.home), "USERPROFILE": str(self.home),
                    "OVERLEG_BRUG_MAP": str(self.basis),
                    "ANTIGRAVITY_LS_ADDRESS": self.adres,
                    "ANTIGRAVITY_CSRF_TOKEN": self.token,
                    "STUB_RESULTAAT": str(self.resultaat), "STUB_KIND_MARKER": str(self.marker)}
        self.stub = self.root / "overleg_stub"
        self.stub.write_text(STUB.replace("{python}", sys.executable), encoding="utf-8")
        self.stub.chmod(0o700)
        self.env["OVERLEG_BRUG_OVERLEG"] = str(self.stub)
        omgevingspatch = mock.patch.dict(os.environ, self.env, clear=True)
        omgevingspatch.start()
        self.addCleanup(omgevingspatch.stop)

    def cli(self, *argumenten, invoer="", env=None, timeout=15):
        return subprocess.run([sys.executable, str(HIER / "brug.py"), *argumenten],
                              input=invoer, capture_output=True, text=True,
                              env=env or self.env, timeout=timeout)

    def luisteraar(self, *argumenten):
        return subprocess.Popen([sys.executable, str(HIER / "brug.py"), "luister", *argumenten],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                env=self.env)

    def wacht_op(self, pad, timeout=5):
        einde = time.monotonic() + timeout
        while not pad.exists():
            self.assertLess(time.monotonic(), einde, f"{pad} verscheen niet")
            time.sleep(0.02)

    def stop(self, proces):
        if proces.poll() is None:
            proces.send_signal(signal.SIGINT)
        uit, fout = proces.communicate(timeout=5)
        self.assertEqual(proces.returncode, 0, fout)
        return uit, fout

    def fake_hartslag(self, ouderdom=0):
        brug.maak_mappen(self.basis)
        brug.schrijf_json(self.basis / "hartslag.json", {
            "pid": os.getpid(), "starttijd": "2026-10-17T12:00:00Z",
            "laatste_tik": time.time() - ouderdom, "versie": 1})

    def taak(self, nummer=1, **wijzigingen):
        brug.maak_mappen(self.basis)
        taak_id = f"20261017T120000000000-{nummer:012x}"
        gegevens = {"id": taak_id, "werkmap": str(self.werk),
                    "rapport": str(self.rapport), "titel": "Controle",
                    "opdracht": "Lees de afspraak.", "opties": {}}
        gegevens.update(wijzigingen)
        brug.schrijf_json(brug._statuspad(self.basis / "wachtrij", taak_id),
                         brug._status(taak_id, "wachtrij"))
        brug.schrijf_json(self.basis / "wachtrij" / f"{taak_id}.json", gegevens)
        return taak_id

    @unittest.skipUnless(os.name == "posix", "luisteraar werkt alleen op macOS/Linux")
    def test_luisteraar_weigert_zonder_antigravity(self):
        env = self.env.copy()
        env.pop("ANTIGRAVITY_LS_ADDRESS")
        env.pop("ANTIGRAVITY_CSRF_TOKEN")
        uit = self.cli("luister", "--eenmalig", env=env)
        self.assertEqual(uit.returncode, 2)
        self.assertIn("Terminal van Antigravity", uit.stderr)
        self.assertFalse(self.basis.exists())

    def test_hartslag_verloopt_en_indienen_weigert(self):
        self.fake_hartslag(61)
        self.assertFalse(brug.brug_leeft(self.basis))
        uit = self.cli("indienen", "-C", str(self.werk), "-o", str(self.rapport),
                       "-t", "Controle", invoer="Lees dit.")
        self.assertEqual(uit.returncode, 2)
        self.assertIn("~/dev/globaal-ai-debat/brug.sh", uit.stderr)
        self.assertFalse(list((self.basis / "wachtrij").glob("*.json")))

    def test_indienen_uit_bestand_en_opties_direct_getoetst(self):
        self.fake_hartslag()
        opdrachtbestand = self.root / "opdracht.md"
        opdrachtbestand.write_text("Lees de afspraak uit het bestand.\n", encoding="utf-8")
        uit = self.cli("indienen", "-C", str(self.werk), "-o", str(self.rapport),
                       "-t", "Controle", "--bestand", str(opdrachtbestand), "-b", "3")
        self.assertEqual(uit.returncode, 0, uit.stderr)
        taak_id = uit.stdout.strip()
        self.assertRegex(taak_id, brug.ID)
        job = json.loads((self.basis / "wachtrij" / f"{taak_id}.json").read_text())
        self.assertEqual(job["opdracht"], opdrachtbestand.read_text())
        self.assertEqual(job["opties"], {"b": 3})
        self.assertTrue(brug._statuspad(self.basis / "wachtrij", taak_id).is_file())
        ongeldig = self.cli("indienen", "-C", str(self.werk), "-o", str(self.rapport),
                            "-t", "Controle", "-G", "ultra", invoer="Lees dit.")
        self.assertEqual(ongeldig.returncode, 2)
        self.assertIn("denkniveau", ongeldig.stderr)
        self.assertEqual(len(list((self.basis / "wachtrij").glob("*.status.json"))), 1)

    @unittest.skipUnless(os.name == "posix", "luisteraar werkt alleen op macOS/Linux")
    def test_witte_lijst_en_bestandsrechten_naar_fout(self):
        onbekend = self.taak(1, extra="geen")
        optie = self.taak(2, opties={"vrije_vlag": "--doe-iets"})
        shell = self.taak(3, opties={"m": "gpt;touch"})
        buiten_werk = self.root / "buiten"
        buiten_werk.mkdir()
        werkmap = self.taak(4, werkmap=str(buiten_werk))
        rapport = self.taak(5, rapport=str(self.root / "buiten.md"))
        werelden = self.taak(6)
        (self.basis / "wachtrij" / f"{werelden}.json").chmod(0o666)
        symlink = self.taak(7)
        job = self.basis / "wachtrij" / f"{symlink}.json"
        echt = self.root / "echt.json"
        job.rename(echt)
        try:
            job.symlink_to(echt)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks niet beschikbaar")
        uit = self.cli("luister", "--eenmalig")
        self.assertEqual(uit.returncode, 0, uit.stderr)
        for taak_id in (onbekend, optie, shell, werkmap, rapport, werelden, symlink):
            with self.subTest(taak_id=taak_id):
                status = json.loads(brug._statuspad(self.basis / "fout", taak_id).read_text())
                self.assertEqual(status["exitcode"], 2)
                self.assertTrue((self.basis / "fout" / f"{taak_id}.json").exists() or
                                (self.basis / "fout" / f"{taak_id}.json").is_symlink())
        self.assertFalse(self.resultaat.exists())
        self.assertFalse(self.rapport.exists())

    @unittest.skipUnless(os.name == "posix", "eigenaarschap via uid")
    def test_vreemde_eigenaar_geweigerd(self):
        taak_id = self.taak()
        job = self.basis / "wachtrij" / f"{taak_id}.json"
        with mock.patch.object(brug.os, "getuid", return_value=os.getuid() + 1):
            with self.assertRaisesRegex(brug.BrugFout, "huidige gebruiker"):
                brug._lees_json_veilig(job)

    @unittest.skipUnless(os.name == "posix", "atomisch claimen vereist POSIX")
    def test_twee_claims_en_een_luisteraar(self):
        taak_id = self.taak()
        uitslagen = []
        start = threading.Event()

        def claim():
            start.wait()
            uitslagen.append(brug.claim_oudste(self.basis))

        draden = [threading.Thread(target=claim) for _ in range(2)]
        for draad in draden:
            draad.start()
        start.set()
        for draad in draden:
            draad.join(5)
        self.assertCountEqual(uitslagen, [taak_id, None])
        (self.basis / "bezig" / f"{taak_id}.json").unlink()
        proces = self.luisteraar()
        try:
            self.wacht_op(self.basis / "hartslag.json")
            dubbel = self.cli("luister", "--eenmalig")
            self.assertEqual(dubbel.returncode, 2)
            self.assertIn("al een luisteraar", dubbel.stderr)
        finally:
            self.stop(proces)
        self.assertFalse((self.basis / "hartslag.json").exists())

    @unittest.skipUnless(os.name == "posix", "nep-overleg is een POSIX-script")
    def test_volledige_ronde_en_geen_geheimen(self):
        proces = self.luisteraar()
        try:
            hartslag = self.basis / "hartslag.json"
            self.wacht_op(hartslag)
            slag = json.loads(hartslag.read_text())
            self.assertEqual(set(slag), {"pid", "starttijd", "laatste_tik", "versie"})
            self.assertEqual(stat.S_IMODE(self.basis.stat().st_mode), 0o700)
            uit = self.cli("indienen", "-C", str(self.werk), "-o", str(self.rapport),
                           "-t", "Controle", "-b", "2", "-m", "gpt-6-sol", "-e", "high",
                           "-g", "gemini-4-argon", "-G", "medium", "-c", "opus",
                           "-E", "max", "-T", "60", "--met-claude", "--wacht",
                           invoer="Lees de afspraak.")
            self.assertEqual(uit.returncode, 0, uit.stderr)
            self.assertIn(str(self.rapport), uit.stdout)
            self.assertTrue(self.rapport.is_file())
            bewijs = json.loads(self.resultaat.read_text())
            self.assertEqual(bewijs["opdracht"], "Lees de afspraak.")
            self.assertEqual(bewijs["cwd"], str(self.werk.resolve()))
            self.assertTrue(bewijs["heeft_adres"] and bewijs["heeft_token"])
            self.assertIn("--met-claude", bewijs["args"])
            self.assertEqual(bewijs["args"][bewijs["args"].index("-T") + 1], "60")
            status = self.cli("status")
            self.assertIn("Brug: actief", status.stdout)
            self.assertIn("Laatste uitkomsten", status.stdout)
            for pad in self.basis.rglob("*"):
                if pad.is_file():
                    inhoud = pad.read_bytes()
                    self.assertNotIn(self.token.encode(), inhoud, str(pad))
                    self.assertNotIn(self.adres.encode(), inhoud, str(pad))
        finally:
            self.stop(proces)
        self.assertFalse((self.basis / "hartslag.json").exists())

    @unittest.skipUnless(os.name == "posix", "nep-overleg is een POSIX-script")
    def test_wacht_geeft_foutcode_van_overleg(self):
        self.env["STUB_MODE"] = "fout"
        proces = self.luisteraar()
        try:
            self.wacht_op(self.basis / "hartslag.json")
            uit = self.cli("indienen", "-C", str(self.werk), "-o", str(self.rapport),
                           "-t", "Controle", "--wacht", invoer="Lees dit.")
            self.assertEqual(uit.returncode, 7, uit.stderr)
            self.assertIn("fout (exitcode 7)", uit.stdout)
        finally:
            self.stop(proces)

    @unittest.skipUnless(os.name == "posix", "procesgroepen vereisen POSIX")
    def test_tijdslimiet_stopt_hele_procesgroep(self):
        self.env["STUB_MODE"] = "sleep"
        taak_id = self.taak()
        uit = self.cli("luister", "--eenmalig", "--tijdslimiet", "0.25", timeout=10)
        self.assertEqual(uit.returncode, 0, uit.stderr)
        status = json.loads(brug._statuspad(self.basis / "fout", taak_id).read_text())
        self.assertEqual(status["exitcode"], 124)
        self.assertIn("tijdslimiet", status["reden"])
        time.sleep(1.3)
        self.assertFalse(self.marker.exists(), "kindproces bleef na de tijdslimiet actief")
        self.assertFalse((self.basis / "hartslag.json").exists())


if __name__ == "__main__":
    unittest.main()
