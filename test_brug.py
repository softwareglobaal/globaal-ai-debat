"""Overleg-brug met alleen tijdelijke mappen en een nep-overlegscript."""

import json
import http.server
import os
import signal
import shutil
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
import signal
import subprocess
import sys
import time
from pathlib import Path

args = sys.argv[1:]
opdracht = sys.stdin.read()
with open(os.environ['STUB_STARTS'], 'a', encoding='utf-8') as starts:
    starts.write(opdracht + '\\n')
if (not os.environ.get('ANTIGRAVITY_LS_ADDRESS')
        or not os.environ.get('ANTIGRAVITY_CSRF_TOKEN')):
    sys.exit(19)
if os.environ.get('STUB_MODE') == 'nested':
    kind = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                            start_new_session=True)
    def stop_kind(nummer, _frame):
        time.sleep(1.2)  # Geef het overleg tijd om een eigen procesgroep op te ruimen.
        try:
            os.killpg(kind.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        kind.wait(timeout=3)
        sys.exit(128 + nummer)
    signal.signal(signal.SIGTERM, stop_kind)
    signal.signal(signal.SIGINT, stop_kind)
    Path(os.environ['STUB_KIND_PID']).write_text(str(kind.pid))
    kind.wait(timeout=30)
if os.environ.get('STUB_MODE') == 'sleep':
    subprocess.Popen([sys.executable, '-c',
                      'import time; from pathlib import Path; time.sleep(1.2); Path(' +
                      repr(os.environ['STUB_KIND_MARKER']) + ').write_text("leeft")'])
    time.sleep(30)
if os.environ.get('STUB_MODE') == 'stop_with_log':
    print('uitvoer voor het stopsignaal', flush=True)
    Path(os.environ['STUB_READY']).write_text('klaar')
    for tik in range(300):
        # Atomisch: de test leest dit bestand terwijl het geschreven wordt.
        tijdelijk = Path(os.environ['STUB_TICKS'] + '.tmp')
        tijdelijk.write_text(str(tik))
        os.replace(tijdelijk, os.environ['STUB_TICKS'])
        time.sleep(0.1)
if os.environ.get('STUB_MODE') == 'fout':
    print('bewuste fout')
    sys.exit(7)
rapport = Path(args[args.index('-o') + 1])
rapport.parent.mkdir(parents=True, exist_ok=True)
rapport.write_text('# Stubrapport\\n', encoding='utf-8')
Path(os.environ['STUB_RESULTAAT']).write_text(json.dumps({
    'args': args, 'opdracht': opdracht, 'cwd': os.getcwd(),
    'luisteraar_pid': os.getppid(),
    'heeft_adres': bool(os.environ.get('ANTIGRAVITY_LS_ADDRESS')),
    'heeft_token': bool(os.environ.get('ANTIGRAVITY_CSRF_TOKEN')),
}), encoding='utf-8')
print(os.environ['ANTIGRAVITY_CSRF_TOKEN'])
print(os.environ['ANTIGRAVITY_LS_ADDRESS'], file=sys.stderr)
print(json.dumps(os.environ['ANTIGRAVITY_CSRF_TOKEN']))
print(json.dumps(os.environ['ANTIGRAVITY_LS_ADDRESS']))
"""


class BrugTests(unittest.TestCase):
    ZONDER_SERVER = {
        "test_luisteraar_weigert_zonder_antigravity",
        "test_hartslag_verloopt_en_indienen_weigert",
        "test_indienen_uit_bestand_en_opties_direct_getoetst",
        "test_vreemde_eigenaar_geweigerd",
        "test_onbereikbaar_bij_start_stopt_direct",
        "test_toegang_interval_grenzen",
        "test_geheimen_weg_stript_omgeving",
        "test_levende_reserve_houdt_brug_beschikbaar",
        "test_zombie_reserve_houdt_brug_niet_levend",
        "test_nieuwe_luisteraar_sluit_verweesde_taak_af",
        "test_opvolger_behoudt_geschreven_eindstatus",
        "test_signaal_tijdens_taak_bewaart_log_en_eindstatus",
        "test_installer_stopt_niet_als_taak_in_wachtrij_komt",
        "test_installer_hervat_na_taak_tijdens_pauze",
        "test_toegang_weigert_niet_lokale_adressen_zonder_verzoek",
        "test_wachtende_indiener_herstelt_verweesde_taak_zonder_luisteraar",
        "test_wachtende_indiener_trekt_taak_in_zonder_brug",
        "test_eenmalig_wacht_na_een_slechte_meting_op_herstel",
        "test_stop_procesgroep_signaleert_alleen_niet_opgeruimde_leider",
    }

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
        self.kind_pid = self.root / "kind.pid"
        self.ready = self.root / "stub-ready"
        self.ticks = self.root / "stub-ticks"
        self.starts = self.root / "stub-starts.txt"
        self.token = "HERKENBARE-NEPSLEUTEL-2026-TEST"
        self.server_code = 200
        self.redirect_to = None
        self.served_codes = []
        self.probes = 0
        self.server = None
        self.adres = "127.0.0.1:0"
        if self._testMethodName not in self.ZONDER_SERVER:
            try:
                self.start_server()
            except PermissionError as exc:
                # Alleen in een afgeschermde sandbox overslaan; in de CI moet dit falen, niet verdwijnen.
                if os.environ.get("CI"):
                    raise
                self.skipTest(f"loopbackpoort geblokkeerd: {exc}")
        self.env = {**os.environ, "HOME": str(self.home), "USERPROFILE": str(self.home),
                    "OVERLEG_BRUG_MAP": str(self.basis),
                    "ANTIGRAVITY_LS_ADDRESS": self.adres,
                    "ANTIGRAVITY_CSRF_TOKEN": self.token,
                    "STUB_RESULTAAT": str(self.resultaat), "STUB_KIND_MARKER": str(self.marker),
                    "STUB_KIND_PID": str(self.kind_pid), "STUB_STARTS": str(self.starts)}
        self.env["STUB_READY"] = str(self.ready)
        self.env["STUB_TICKS"] = str(self.ticks)
        self.env.pop("ANTIGRAVITY_SIDECAR_WEB_PORT", None)
        self.env.pop("ANTIGRAVITY_EXECUTABLE_DATA_DIR", None)
        self.stub = self.root / "overleg_stub"
        self.stub.write_text(STUB.replace("{python}", sys.executable), encoding="utf-8")
        self.stub.chmod(0o700)
        self.env["OVERLEG_BRUG_OVERLEG"] = str(self.stub)
        omgevingspatch = mock.patch.dict(os.environ, self.env, clear=True)
        omgevingspatch.start()
        self.addCleanup(omgevingspatch.stop)

    def start_server(self):
        test = self

        class Antigravity(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                # Eerst de body lezen: een ongelezen body laat de server de verbinding met RST
                # sluiten, en dan ziet de luisteraar af en toe "weg" (wisselvallige test).
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                test.probes += 1
                code = test.server_code
                test.served_codes.append(code)
                self.send_response(code)
                if test.redirect_to:
                    self.send_header("Location", test.redirect_to)
                self.end_headers()

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Antigravity)
        self.adres = f"127.0.0.1:{self.server.server_port}"
        self.serverdraad = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.serverdraad.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.serverdraad.join(timeout=2)
            self.server = None

    def cli(self, *argumenten, invoer="", env=None, timeout=15):
        return subprocess.run([sys.executable, str(HIER / "brug.py"), *argumenten],
                              input=invoer, capture_output=True, text=True,
                              env=env or self.env, timeout=timeout)

    def luisteraar(self, *argumenten, env=None):
        return subprocess.Popen([sys.executable, str(HIER / "brug.py"), "luister", *argumenten],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                env=env or self.env)

    def luisteraar_zonder_netwerk(self, *argumenten, env=None):
        helpermap = self.root / "nep-luisteraar"
        helpermap.mkdir(exist_ok=True)
        helper = helpermap / "brug.py"
        helper.write_text(
            "import sys\n"
            f"sys.path.insert(0, {str(HIER)!r})\n"
            "import brug\n"
            "brug.toegang = lambda *args, **kwargs: 'ok'\n"
            "sys.exit(brug.main(sys.argv[1:]))\n", encoding="utf-8")
        return subprocess.Popen([sys.executable, str(helper), "luister", *argumenten],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                env=env or self.env)

    def wacht_op(self, pad, timeout=5):
        einde = time.monotonic() + timeout
        while not pad.exists():
            self.assertLess(time.monotonic(), einde, f"{pad} verscheen niet")
            time.sleep(0.02)

    def wacht_tot(self, voorwaarde, timeout=5):
        einde = time.monotonic() + timeout
        while not voorwaarde():
            self.assertLess(time.monotonic(), einde, "Voorwaarde werd niet op tijd waar")
            time.sleep(0.02)

    def stop(self, proces):
        if proces.poll() is None:
            proces.send_signal(signal.SIGINT)
        uit, fout = proces.communicate(timeout=5)
        self.assertEqual(proces.returncode, 0, fout)
        return uit, fout

    def reserve_van(self, pid):
        for pad in self.basis.glob("reserve.*.json"):
            try:
                gegevens = json.loads(pad.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if gegevens.get("pid") == pid:
                return pad, gegevens
        return None

    def proces_actief(self, pid):
        toestand = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)],
                                  capture_output=True, text=True, timeout=2).stdout.strip()
        return bool(toestand) and not toestand.startswith("Z")

    def ruim_kind_op(self):
        if not self.kind_pid.exists():
            return
        pid = int(self.kind_pid.read_text())
        if self.proces_actief(pid):
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def installatie_kopie(self):
        repo = self.root / "installatie-repo"
        repo.mkdir()
        for naam in ("installeer_sidecar.sh", "brug.sh", "brug.py"):
            shutil.copy2(HIER / naam, repo / naam)
        (repo / ".venv" / "bin").mkdir(parents=True)
        (repo / ".venv" / "bin" / "python").symlink_to(sys.executable)
        config = self.home / "config"
        config.mkdir()
        env = {**self.env, "ANTIGRAVITY_CONFIG_DIR": str(config)}
        return repo / "installeer_sidecar.sh", env

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

    def test_geheimen_weg_stript_omgeving(self):
        rauw_token = f" \t{self.token} "
        rauw_adres = f" {self.adres}\t "
        tekst = " | ".join((rauw_token, rauw_token.strip(),
                            json.dumps(rauw_token)[1:-1], rauw_adres,
                            rauw_adres.strip(), json.dumps(rauw_adres)[1:-1]))
        with mock.patch.dict(os.environ, {"ANTIGRAVITY_CSRF_TOKEN": rauw_token,
                                          "ANTIGRAVITY_LS_ADDRESS": rauw_adres}):
            gezuiverd = brug.geheimen_weg(tekst)
        self.assertNotIn(self.token, gezuiverd)
        self.assertNotIn(self.adres, gezuiverd)
        self.assertNotIn(json.dumps(rauw_token)[1:-1], gezuiverd)
        self.assertNotIn(json.dumps(rauw_adres)[1:-1], gezuiverd)

    def test_levende_reserve_houdt_brug_beschikbaar(self):
        brug.maak_mappen(self.basis)
        pad = self.basis / f"reserve.{os.getpid()}.json"
        gegevens = {"pid": os.getpid(), "starttijd": "test", "laatste_tik": time.time(),
                    "versie": brug.VERSIE, "bron": "sidecar"}
        brug.schrijf_json(pad, gegevens)
        self.assertTrue(brug.brug_leeft(self.basis))
        status = self.cli("status")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn("reserve", status.stdout.lower())
        gegevens["laatste_tik"] -= 61
        brug.schrijf_json(pad, gegevens)
        self.assertFalse(brug.brug_leeft(self.basis))

    @unittest.skipUnless(os.name == "posix", "zombiestatus vereist POSIX")
    def test_zombie_reserve_houdt_brug_niet_levend(self):
        brug.maak_mappen(self.basis)
        brug.schrijf_json(self.basis / f"reserve.{os.getpid()}.json", {
            "pid": os.getpid(), "starttijd": "test", "laatste_tik": time.time(),
            "versie": brug.VERSIE, "bron": "sidecar"})
        nep_ps = subprocess.CompletedProcess(["/bin/ps"], 0, stdout="Z\n", stderr="")
        with mock.patch.object(brug.subprocess, "run", return_value=nep_ps):
            self.assertFalse(brug.brug_leeft(self.basis))

    @unittest.skipUnless(os.name == "posix", "brug werkt alleen op macOS/Linux; Windows-paden bevatten een backslash")
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
            self.assertEqual(set(slag), {"pid", "starttijd", "laatste_tik", "versie", "bron"})
            self.assertEqual(slag["versie"], 2)
            self.assertEqual(slag["bron"], "terminal")
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
    def test_geheimen_met_spaties_niet_in_uitvoer_of_bestanden(self):
        rauw_token = f" \t{self.token} "
        rauw_adres = f" {self.adres} "
        self.env["ANTIGRAVITY_CSRF_TOKEN"] = rauw_token
        self.env["ANTIGRAVITY_LS_ADDRESS"] = rauw_adres
        proces = self.luisteraar()
        try:
            hartslag = self.basis / "hartslag.json"
            self.wacht_op(hartslag)
            indiening = self.cli("indienen", "-C", str(self.werk), "-o", str(self.rapport),
                                 "-t", "Afscherming", "--wacht", invoer="Lees dit.")
            self.assertEqual(indiening.returncode, 0, indiening.stderr)
            status = self.cli("status")
            uit, fout = self.stop(proces)
            inhoud = "\n".join((indiening.stdout, indiening.stderr,
                                  status.stdout, status.stderr, uit, fout))
            for pad in self.basis.rglob("*"):
                if pad.is_file():
                    inhoud += "\n" + pad.read_text(encoding="utf-8")
            for geheim in (self.token, self.adres, rauw_token,
                           json.dumps(rauw_token)[1:-1], json.dumps(rauw_adres)[1:-1]):
                self.assertNotIn(geheim, inhoud)
        finally:
            if proces.poll() is None:
                self.stop(proces)

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

    @unittest.skipUnless(os.name == "posix", "signalen en procesgroepen vereisen POSIX")
    def test_sigterm_stopt_overleg_met_eigen_kleinkind_en_ontgrendelt(self):
        self.env["STUB_MODE"] = "nested"
        taak_id = self.taak()
        proces = self.luisteraar()
        try:
            self.wacht_op(self.kind_pid)
            kind = int(self.kind_pid.read_text())
            self.assertTrue(self.proces_actief(kind))
            proces.send_signal(signal.SIGTERM)
            _, fout = proces.communicate(timeout=10)
            self.assertIn(proces.returncode, (0, 130, 143), fout)
            status = json.loads(brug._statuspad(self.basis / "fout", taak_id).read_text())
            self.assertIn(status["exitcode"], (130, 143))
            self.assertEqual(status["reden"], "Luisteraar gestopt")
            self.wacht_tot(lambda: not self.proces_actief(kind), timeout=5)
            self.assertFalse((self.basis / "hartslag.json").exists())
            opvolger = self.cli("luister", "--eenmalig", timeout=5)
            self.assertEqual(opvolger.returncode, 0, opvolger.stderr)
        finally:
            if proces.poll() is None:
                proces.kill()
                proces.communicate(timeout=5)
            self.ruim_kind_op()

    @unittest.skipUnless(os.name == "posix", "signalen vereisen POSIX")
    def test_signaal_tijdens_taak_bewaart_log_en_eindstatus(self):
        self.env["STUB_MODE"] = "stop_with_log"
        taak_id = self.taak()
        proces = self.luisteraar_zonder_netwerk()
        try:
            self.wacht_op(self.ready)
            proces.send_signal(signal.SIGTERM)
            proces.send_signal(signal.SIGINT)  # Ook een tweede stop mag de verplaatsing niet afbreken.
            _, fout = proces.communicate(timeout=10)
            self.assertEqual(proces.returncode, 0, fout)
            status = json.loads(brug._statuspad(self.basis / "fout", taak_id).read_text())
            self.assertEqual((status["toestand"], status["exitcode"], status["reden"]),
                             ("fout", 130, "Luisteraar gestopt"))
            self.assertIn("uitvoer voor het stopsignaal",
                          brug._logpad(self.basis / "fout", taak_id).read_text())
            self.assertFalse(list((self.basis / "bezig").iterdir()))
            self.assertFalse((self.basis / "hartslag.json").exists())
        finally:
            if proces.poll() is None:
                proces.kill()
                proces.communicate(timeout=5)

    @unittest.skipUnless(os.name == "posix", "signalen en procesgroepen vereisen POSIX")
    def test_veroudering_stopt_overleg_met_eigen_kleinkind(self):
        self.env["STUB_MODE"] = "nested"
        taak_id = self.taak()
        proces = self.luisteraar("--toegang-interval", "0.2")
        try:
            self.wacht_op(self.kind_pid)
            kind = int(self.kind_pid.read_text())
            self.server_code = 403
            _, fout = proces.communicate(timeout=10)
            self.assertEqual(proces.returncode, 3, fout)
            status = json.loads(brug._statuspad(self.basis / "fout", taak_id).read_text())
            self.assertEqual(status["exitcode"], 3)
            self.wacht_tot(lambda: not self.proces_actief(kind), timeout=5)
            self.assertFalse((self.basis / "hartslag.json").exists())
        finally:
            if proces.poll() is None:
                proces.kill()
                proces.communicate(timeout=5)
            self.ruim_kind_op()

    @unittest.skipUnless(os.name == "posix", "luisterslot vereist POSIX")
    def test_nieuwe_luisteraar_sluit_verweesde_taak_af(self):
        taak_id = self.taak()
        self.assertEqual(brug.claim_oudste(self.basis), taak_id)
        with mock.patch.object(brug, "toegang", return_value="ok"):
            self.assertEqual(brug.main(["luister", "--eenmalig"]), 0)
        status = json.loads(brug._statuspad(self.basis / "fout", taak_id).read_text())
        self.assertEqual(status["toestand"], "fout")
        self.assertEqual(status["exitcode"], 3)
        self.assertEqual(status["reden"], "Afgebroken: vorige luisteraar stopte")
        self.assertFalse((self.basis / "bezig" / f"{taak_id}.json").exists())
        self.assertFalse(self.starts.exists())

    @unittest.skipUnless(os.name == "posix", "luisterslot vereist POSIX")
    def test_opvolger_behoudt_geschreven_eindstatus(self):
        taak_id = self.taak()
        self.assertEqual(brug.claim_oudste(self.basis), taak_id)
        brug.schrijf_atomisch(brug._logpad(self.basis / "bezig", taak_id), b"voltooid\n")
        brug.schrijf_json(brug._statuspad(self.basis / "bezig", taak_id),
                         brug._status(taak_id, "klaar", exitcode=0, rapport=str(self.rapport)))
        brug.schrijf_json(brug._statuspad(self.basis / "wachtrij", taak_id),
                         brug._status(taak_id, "wachtrij"))
        with mock.patch.object(brug, "toegang", return_value="ok"):
            self.assertEqual(brug.main(["luister", "--eenmalig"]), 0)
        status = json.loads(brug._statuspad(self.basis / "klaar", taak_id).read_text())
        self.assertEqual((status["toestand"], status["exitcode"]), ("klaar", 0))
        self.assertEqual(brug._logpad(self.basis / "klaar", taak_id).read_text(), "voltooid\n")
        self.assertTrue((self.basis / "klaar" / f"{taak_id}.json").exists())
        self.assertFalse(brug._statuspad(self.basis / "wachtrij", taak_id).exists())
        self.assertFalse(list((self.basis / "bezig").iterdir()))
        self.assertFalse(self.starts.exists())

    def test_toegang_classificeert_http_en_onbereikbaar(self):
        self.assertEqual(brug.toegang(self.adres, self.token), "ok")
        self.server_code = 401
        self.assertEqual(brug.toegang(self.adres, self.token), "geweigerd")
        self.server_code = 403
        self.assertEqual(brug.toegang(self.adres, self.token), "geweigerd")
        self.server_code = 404
        self.assertEqual(brug.toegang(self.adres, self.token), "ok")
        self.server_code = 500
        self.assertEqual(brug.toegang(self.adres, self.token), "ok")
        self.stop_server()
        self.assertEqual(brug.toegang(self.adres, self.token, timeout=0.2), "weg")
        self.assertEqual(brug.toegang("geen geldig adres", self.token, timeout=0.2), "weg")

    def test_toegang_weigert_niet_lokale_adressen_zonder_verzoek(self):
        for adres in ("example.com:80", "127.0.0.1:80/pad",
                      "gebruiker@localhost:80", "localhost:80?x=1"):
            with self.subTest(adres=adres), mock.patch.object(brug.urlrequest, "build_opener") as opener:
                self.assertEqual(brug.toegang(adres, self.token), "weg")
                opener.assert_not_called()
        self.assertTrue(brug.lokaal_adres("[::1]:53510"))

    def test_toegang_gebruikt_geen_proxy_of_omleiding(self):
        with mock.patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:1",
                                              "NO_PROXY": "", "no_proxy": ""}):
            self.assertEqual(brug.toegang(self.adres, self.token), "ok")
            self.assertEqual(self.probes, 1)
            self.server_code = 302
            self.redirect_to = f"http://{self.adres}/omleiding"
            self.assertEqual(brug.toegang(self.adres, self.token), "weg")
            self.assertEqual(self.probes, 2, "Heartbeat volgde de omleiding")

    @unittest.skipUnless(os.name == "posix", "luisterslot vereist POSIX")
    def test_reserve_neemt_na_eerste_luisteraar_over(self):
        eerste = self.luisteraar("--toegang-interval", "0.2")
        tweede = None
        try:
            hartslag = self.basis / "hartslag.json"
            self.wacht_op(hartslag)
            tweede = self.luisteraar("--wacht-op-slot", "--toegang-interval", "0.2")
            self.wacht_tot(lambda: self.probes >= 2)
            self.assertIsNone(tweede.poll())
            self.assertEqual(json.loads(hartslag.read_text())["pid"], eerste.pid)
            eerste_taak = self.taak(1)
            self.wacht_op(brug._statuspad(self.basis / "klaar", eerste_taak))
            self.assertEqual(json.loads(hartslag.read_text())["pid"], eerste.pid)
            self.stop(eerste)
            self.wacht_tot(lambda: hartslag.exists() and
                           json.loads(hartslag.read_text())["pid"] == tweede.pid, timeout=7)
            tweede_taak = self.taak(2)
            self.wacht_op(brug._statuspad(self.basis / "klaar", tweede_taak))
            self.assertEqual(json.loads(hartslag.read_text())["pid"], tweede.pid)
            uit, _ = self.stop(tweede)
            self.assertEqual(uit.count("deze wacht als reserve"), 1)
        finally:
            for proces in (eerste, tweede):
                if proces is not None and proces.poll() is None:
                    proces.send_signal(signal.SIGINT)
                    proces.communicate(timeout=5)

    @unittest.skipUnless(os.name == "posix", "processtop vereist POSIX")
    def test_wachtende_indiener_krijgt_rapport_tijdens_reserve_overname(self):
        eerste = self.luisteraar()
        tweede = None
        indiener = None
        reserve_gepauzeerd = False
        try:
            self.wacht_op(self.basis / "hartslag.json")
            tweede = self.luisteraar("--wacht-op-slot")
            self.wacht_tot(lambda: self.reserve_van(tweede.pid) is not None)
            reservepad, reserve = self.reserve_van(tweede.pid)
            self.assertEqual(set(reserve), {"pid", "starttijd", "laatste_tik", "versie", "bron"})
            self.assertEqual(reserve["bron"], "terminal")
            tweede.send_signal(signal.SIGSTOP)
            reserve_gepauzeerd = True
            self.stop(eerste)
            self.assertFalse((self.basis / "hartslag.json").exists())
            self.assertTrue(brug.brug_leeft(self.basis))
            self.assertIn("reserve", self.cli("status").stdout.lower())
            opdrachtbestand = self.root / "overdracht.md"
            opdrachtbestand.write_text("Overdracht", encoding="utf-8")
            indiener = subprocess.Popen(
                [sys.executable, str(HIER / "brug.py"), "indienen", "-C", str(self.werk),
                 "-o", str(self.rapport), "-t", "Overdracht", "--bestand",
                 str(opdrachtbestand), "--wacht"], stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, env=self.env)
            self.wacht_tot(lambda: any(not p.name.endswith(".status.json")
                                       for p in (self.basis / "wachtrij").glob("*.json")))
            self.assertIsNone(indiener.poll())
            tweede.send_signal(signal.SIGCONT)
            reserve_gepauzeerd = False
            uit, fout = indiener.communicate(timeout=10)
            self.assertEqual(indiener.returncode, 0, fout)
            self.assertIn(str(self.rapport), uit)
            self.assertEqual(self.starts.read_text().splitlines(), ["Overdracht"])
            self.assertEqual(json.loads(self.resultaat.read_text())["luisteraar_pid"], tweede.pid)
            self.wacht_tot(lambda: not reservepad.exists())
        finally:
            if reserve_gepauzeerd and tweede is not None and tweede.poll() is None:
                tweede.send_signal(signal.SIGCONT)
            if indiener is not None and indiener.poll() is None:
                indiener.kill()
                indiener.communicate(timeout=5)
            for proces in (eerste, tweede):
                if proces is not None and proces.poll() is None:
                    self.stop(proces)

    @unittest.skipUnless(os.name == "posix", "atomische verplaatsing vereist POSIX")
    def test_wachtende_indiener_trekt_taak_in_zonder_brug(self):
        self.fake_hartslag()
        opdrachtbestand = self.root / "intrekken.md"
        opdrachtbestand.write_text("Niet later uitvoeren", encoding="utf-8")
        indiener = subprocess.Popen(
            [sys.executable, str(HIER / "brug.py"), "indienen", "-C", str(self.werk),
             "-o", str(self.rapport), "-t", "Intrekken", "--bestand",
             str(opdrachtbestand), "--wacht"], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env=self.env)
        try:
            self.wacht_tot(lambda: any(not p.name.endswith(".status.json")
                                       for p in (self.basis / "wachtrij").glob("*.json")))
            taak_id = next(p.name[:-5] for p in (self.basis / "wachtrij").glob("*.json")
                           if not p.name.endswith(".status.json"))
            (self.basis / "hartslag.json").unlink()
            _, fout = indiener.communicate(timeout=5)
            self.assertEqual(indiener.returncode, 2, fout)
            self.assertIn(taak_id, fout)
            status = json.loads(brug._statuspad(self.basis / "fout", taak_id).read_text())
            self.assertEqual(status["toestand"], "fout")
            self.assertEqual(status["exitcode"], 2)
            self.assertEqual(status["reden"], "Ingetrokken: brug draait niet")
            self.assertTrue((self.basis / "fout" / f"{taak_id}.json").exists())
            self.assertFalse((self.basis / "wachtrij" / f"{taak_id}.json").exists())
            with mock.patch.object(brug, "toegang", return_value="ok"):
                self.assertEqual(brug.main(["luister", "--eenmalig"]), 0)
            self.assertFalse(self.starts.exists())
        finally:
            if indiener.poll() is None:
                indiener.kill()
                indiener.communicate(timeout=5)

    @unittest.skipUnless(os.name == "posix", "luisterslot vereist POSIX")
    def test_wachtende_indiener_herstelt_verweesde_taak_zonder_luisteraar(self):
        self.fake_hartslag()
        opdrachtbestand = self.root / "verweesd.md"
        opdrachtbestand.write_text("Lees de afspraak.", encoding="utf-8")
        indiener = subprocess.Popen(
            [sys.executable, str(HIER / "brug.py"), "indienen", "-C", str(self.werk),
             "-o", str(self.rapport), "-t", "Verweesd", "--bestand",
             str(opdrachtbestand), "--wacht"], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env=self.env)
        try:
            self.wacht_tot(lambda: any(not p.name.endswith(".status.json")
                                       for p in (self.basis / "wachtrij").glob("*.json")))
            taak_id = brug.claim_oudste(self.basis)
            self.assertIsNotNone(taak_id)
            (self.basis / "hartslag.json").unlink()
            begin = time.monotonic()
            uit, fout = indiener.communicate(timeout=5)
            self.assertLess(time.monotonic() - begin, 5)
            self.assertEqual(indiener.returncode, 3, fout)
            self.assertIn("fout (exitcode 3)", uit)
            status = json.loads(brug._statuspad(self.basis / "fout", taak_id).read_text())
            self.assertEqual(status["reden"], "Afgebroken: vorige luisteraar stopte")
            self.assertFalse(list((self.basis / "bezig").iterdir()))
        finally:
            if indiener.poll() is None:
                indiener.kill()
                indiener.communicate(timeout=5)

    @unittest.skipUnless(os.name == "posix", "luisterslot vereist POSIX")
    def test_server_weg_ruimt_hartslag_en_slot_op(self):
        proces = self.luisteraar("--toegang-interval", "0.2")
        hartslag = self.basis / "hartslag.json"
        try:
            self.wacht_op(hartslag)
            self.stop_server()
            _, fout = proces.communicate(timeout=5)
            self.assertEqual(proces.returncode, 3, fout)
            self.assertIn("luisteraar stopt", fout)
            self.assertFalse(hartslag.exists())
            self.start_server()
            env = {**self.env, "ANTIGRAVITY_LS_ADDRESS": self.adres}
            opvolger = self.luisteraar("--eenmalig", env=env)
            _, fout = opvolger.communicate(timeout=5)
            self.assertEqual(opvolger.returncode, 0, fout)
        finally:
            if proces.poll() is None:
                self.stop(proces)

    @unittest.skipUnless(os.name == "posix", "luisteraar vereist POSIX")
    def test_token_wordt_na_start_geweigerd(self):
        proces = self.luisteraar("--toegang-interval", "0.2")
        try:
            self.wacht_op(self.basis / "hartslag.json")
            self.server_code = 403
            _, fout = proces.communicate(timeout=5)
            self.assertEqual(proces.returncode, 3, fout)
            self.assertFalse((self.basis / "hartslag.json").exists())
        finally:
            if proces.poll() is None:
                self.stop(proces)

    @unittest.skipUnless(os.name == "posix", "luisteraar vereist POSIX")
    def test_403_bij_start_toetst_alleen_bereikbaarheid(self):
        self.server_code = 403
        proces = self.luisteraar("--toegang-interval", "0.2")
        try:
            self.wacht_op(self.basis / "hartslag.json")
            self.wacht_tot(lambda: self.probes >= 4)
            self.assertIsNone(proces.poll())
            self.stop_server()
            _, fout = proces.communicate(timeout=5)
            self.assertEqual(proces.returncode, 3, fout)
            self.assertEqual(fout.count("alleen bereikbaarheid"), 1)
            self.assertFalse((self.basis / "hartslag.json").exists())
        finally:
            if proces.poll() is None:
                self.stop(proces)

    @unittest.skipUnless(os.name == "posix", "luisteraar vereist POSIX")
    def test_onbereikbaar_bij_start_stopt_direct(self):
        env = {**self.env, "ANTIGRAVITY_LS_ADDRESS": "127.0.0.1:0"}
        uit = self.cli("luister", env=env)
        self.assertEqual(uit.returncode, 3, uit.stderr)
        self.assertFalse((self.basis / "hartslag.json").exists())

    def test_toegang_interval_grenzen(self):
        for interval in ("0.1", "601", "nan"):
            with self.subTest(interval=interval):
                uit = self.cli("luister", "--toegang-interval", interval)
                self.assertEqual(uit.returncode, 2)
                self.assertIn("Toegang-interval", uit.stderr)
        self.assertFalse((self.basis / "hartslag.json").exists())

    @unittest.skipUnless(os.name == "posix", "luisteraar vereist POSIX")
    def test_slechte_meting_claimt_geen_opdracht(self):
        proces = self.luisteraar("--toegang-interval", "0.2")
        try:
            self.wacht_op(self.basis / "hartslag.json")
            voor = self.probes
            self.server_code = 403
            # Pas als de tweede 403-meting binnenkomt is de eerste zeker verwerkt (metingen lopen na elkaar).
            self.wacht_tot(lambda: self.probes > voor + 1)
            taak_id = self.taak()
            _, fout = proces.communicate(timeout=5)
            self.assertEqual(proces.returncode, 3, fout)
            self.assertTrue((self.basis / "wachtrij" / f"{taak_id}.json").is_file())
            self.assertFalse((self.basis / "bezig" / f"{taak_id}.json").exists())
        finally:
            if proces.poll() is None:
                self.stop(proces)

    @unittest.skipUnless(os.name == "posix", "luisteraar vereist POSIX")
    def test_een_slechte_meting_herstelt_snel_bij_wachtende_taak(self):
        proces = self.luisteraar("--toegang-interval", "3")
        try:
            self.wacht_op(self.basis / "hartslag.json")
            self.server_code = 403
            self.wacht_tot(lambda: 403 in self.served_codes, timeout=5)
            time.sleep(0.05)  # De luisteraar moet de 403 eerst als slechte meting verwerken.
            self.server_code = 200
            taak_id = self.taak()
            self.wacht_op(brug._statuspad(self.basis / "klaar", taak_id), timeout=2.3)
            status = json.loads(brug._statuspad(self.basis / "klaar", taak_id).read_text())
            self.assertEqual(status["exitcode"], 0)
        finally:
            if proces.poll() is None:
                self.stop(proces)

    @unittest.skipUnless(os.name == "posix", "luisterslot vereist POSIX")
    def test_eenmalig_wacht_na_een_slechte_meting_op_herstel(self):
        taak_id = self.taak()
        eerste_slechte = threading.Event()
        metingen = []
        uitslag = []
        fouten = []
        echte_neem_slot = brug._neem_slot

        def toegang_zonder_netwerk(_adres, _token, timeout=3):
            uitkomst = "weg" if len(metingen) == 1 else "ok"
            metingen.append(uitkomst)
            if uitkomst == "weg":
                eerste_slechte.set()
            return uitkomst

        def slot_na_slechte_meting(basis):
            if not eerste_slechte.wait(timeout=4):
                raise AssertionError("De eerste slechte meting kwam niet")
            time.sleep(0.08)  # De bewaker rondt zijn meting af voor de hoofdloop start.
            return echte_neem_slot(basis)

        def draai():
            try:
                uitslag.append(brug.main(["luister", "--eenmalig",
                                          "--toegang-interval", "2"]))
            except BaseException as exc:
                fouten.append(exc)

        with mock.patch.object(brug, "toegang", side_effect=toegang_zonder_netwerk), \
                mock.patch.object(brug, "_neem_slot", side_effect=slot_na_slechte_meting):
            draad = threading.Thread(target=draai, daemon=True)
            draad.start()
            draad.join(timeout=7)
        self.assertFalse(draad.is_alive(), "--eenmalig bleef hangen na herstel")
        self.assertFalse(fouten, fouten)
        self.assertEqual(uitslag, [0])
        self.assertGreaterEqual(len(metingen), 3)
        self.assertEqual(metingen[:3], ["ok", "weg", "ok"])
        status = json.loads(brug._statuspad(self.basis / "klaar", taak_id).read_text())
        self.assertEqual(status["exitcode"], 0)
        self.assertEqual(self.starts.read_text().splitlines(), ["Lees de afspraak."])

    @unittest.skipUnless(os.name == "posix", "ouderbewaking vereist POSIX")
    def test_ouder_weg_stopt_met_code_3(self):
        resultaat = self.root / "ouder-code"
        melding = self.root / "ouder-melding"
        pidbestand = self.root / "ouder-pid"
        helper = self.root / "ouder-helper.py"
        helper.write_text(
            "import sys\nfrom pathlib import Path\n"
            f"sys.path.insert(0, {str(HIER)!r})\nimport brug\n"
            f"with open({str(melding)!r}, 'w') as fout:\n"
            "    import contextlib\n"
            "    with contextlib.redirect_stderr(fout):\n"
            "        code = brug.main(['luister', '--ouder-bewaken', '--toegang-interval', '0.2'])\n"
            f"Path({str(resultaat)!r}).write_text(str(code))\n",
            encoding="utf-8")
        starter = (
            "import json, subprocess, sys, time\nfrom pathlib import Path\n"
            f"kind = subprocess.Popen([sys.executable, {str(helper)!r}], "
            "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
            f"Path({str(pidbestand)!r}).write_text(str(kind.pid))\n"
            f"hartslag = Path({str(self.basis / 'hartslag.json')!r})\n"
            "einde = time.monotonic() + 3\n"
            "while time.monotonic() < einde:\n"
            "    try:\n"
            "        if json.loads(hartslag.read_text())['pid'] == kind.pid: break\n"
            "    except (OSError, ValueError, KeyError): pass\n"
            "    time.sleep(0.02)\n")
        ouder = subprocess.Popen([sys.executable, "-c", starter], env=self.env)
        try:
            self.wacht_op(pidbestand)
            ouder.communicate(timeout=5)
            self.wacht_op(resultaat, timeout=5)
            self.assertEqual(resultaat.read_text(), "3")
            self.assertIn("Antigravity is gestopt", melding.read_text())
            self.assertFalse((self.basis / "hartslag.json").exists())
        finally:
            if ouder.poll() is None:
                ouder.terminate()
                ouder.wait(timeout=3)
            if pidbestand.exists() and not resultaat.exists():
                try:
                    os.kill(int(pidbestand.read_text()), signal.SIGTERM)
                except ProcessLookupError:
                    pass

    @unittest.skipUnless(os.name == "posix", "luisteraar vereist POSIX")
    def test_hartslag_bron_en_status(self):
        for bron, extra in (("terminal", {}), ("sidecar", {"ANTIGRAVITY_SIDECAR_WEB_PORT": "123"})):
            with self.subTest(bron=bron):
                env = {**self.env, **extra}
                proces = self.luisteraar(env=env)
                try:
                    hartslag = self.basis / "hartslag.json"
                    self.wacht_tot(lambda: hartslag.exists() and
                                   json.loads(hartslag.read_text()).get("pid") == proces.pid)
                    self.assertEqual(json.loads(hartslag.read_text())["bron"], bron)
                    status = self.cli("status", env=env)
                    self.assertIn(f"bron {bron}", status.stdout)
                finally:
                    self.stop(proces)

    @unittest.skipUnless(os.name == "posix", "overname vereist POSIX-signalen")
    def test_installer_laat_terminal_staan_of_draagt_over(self):
        script, env = self.installatie_kopie()
        eerste = self.luisteraar(env=env)
        reserve = None
        try:
            hartslag = self.basis / "hartslag.json"
            self.wacht_tot(lambda: hartslag.exists() and
                           json.loads(hartslag.read_text()).get("pid") == eerste.pid)
            sidecar_env = {**env, "ANTIGRAVITY_SIDECAR_WEB_PORT": "123"}
            reserve = self.luisteraar("--wacht-op-slot", env=sidecar_env)
            self.wacht_tot(lambda: self.reserve_van(reserve.pid) is not None)
            niet_wachten = subprocess.run(["/bin/bash", str(script), "--niet-wachten"],
                                          capture_output=True, text=True, env=env, timeout=10)
            self.assertEqual(niet_wachten.returncode, 0, niet_wachten.stderr)
            self.assertIn("Sidecar staat klaar als reserve", niet_wachten.stdout)
            self.assertIsNone(eerste.poll())
            laat_staan = subprocess.run(["/bin/bash", str(script), "--laat-staan"],
                                        capture_output=True, text=True, env=env, timeout=10)
            self.assertEqual(laat_staan.returncode, 0, laat_staan.stderr)
            self.assertIn("Sidecar staat klaar als reserve", laat_staan.stdout)
            self.assertIsNone(eerste.poll())
            overname = subprocess.run(["/bin/bash", str(script)], capture_output=True,
                                      text=True, env=env, timeout=12)
            self.assertEqual(overname.returncode, 0, overname.stderr)
            self.assertIn("Oude luisteraar gestopt; sidecar heeft overgenomen", overname.stdout)
            eerste.communicate(timeout=5)
            self.wacht_tot(lambda: hartslag.exists() and
                           json.loads(hartslag.read_text()).get("pid") == reserve.pid)
            self.assertFalse(list(self.basis.glob("reserve.*.json")))
        finally:
            for proces in (eerste, reserve):
                if proces is not None and proces.poll() is None:
                    self.stop(proces)

    @unittest.skipUnless(os.name == "posix", "overname vereist POSIX-signalen")
    def test_installer_stopt_niet_als_taak_in_wachtrij_komt(self):
        script, env = self.installatie_kopie()
        env["STUB_MODE"] = "stop_with_log"
        eerste = self.luisteraar_zonder_netwerk(env=env)
        reserve = None
        installer = None
        try:
            self.wacht_op(self.basis / "hartslag.json")
            reserve = self.luisteraar_zonder_netwerk("--wacht-op-slot", env={
                **env, "ANTIGRAVITY_SIDECAR_WEB_PORT": "123"})
            self.wacht_tot(lambda: self.reserve_van(reserve.pid) is not None)
            taak_id = self.taak()
            installer = subprocess.Popen(["/bin/bash", str(script)],
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         text=True, env=env)
            self.wacht_op(self.ready)
            self.wacht_op(self.ticks)
            eerste_tik = int(self.ticks.read_text())
            time.sleep(0.6)
            self.assertIsNone(eerste.poll(), "oude luisteraar kreeg toch INT")
            self.assertIsNone(installer.poll(), "installer meldde overname tijdens een taak")
            self.assertGreater(int(self.ticks.read_text()), eerste_tik,
                               "oude luisteraar bleef gepauzeerd")
            self.assertTrue((self.basis / "bezig" / f"{taak_id}.json").exists())
        finally:
            if installer is not None and installer.poll() is None:
                installer.terminate()
                installer.communicate(timeout=5)
            for proces in (eerste, reserve):
                if proces is not None and proces.poll() is None:
                    self.stop(proces)

    @unittest.skipUnless(os.name == "posix", "overname vereist POSIX-signalen")
    def test_installer_hervat_na_taak_tijdens_pauze(self):
        script, env = self.installatie_kopie()
        env["STUB_MODE"] = "stop_with_log"
        taak_id = self.taak()
        staging = self.root / "staging"
        staging.mkdir()
        job = self.basis / "wachtrij" / f"{taak_id}.json"
        status = brug._statuspad(self.basis / "wachtrij", taak_id)
        staged_job, staged_status = staging / job.name, staging / status.name
        os.replace(job, staged_job)
        os.replace(status, staged_status)
        eerste = self.luisteraar_zonder_netwerk(env=env)
        reserve = installer = None
        try:
            self.wacht_op(self.basis / "hartslag.json")
            reserve = self.luisteraar_zonder_netwerk("--wacht-op-slot", env={
                **env, "ANTIGRAVITY_SIDECAR_WEB_PORT": "123"})
            self.wacht_tot(lambda: self.reserve_van(reserve.pid) is not None)
            nepps = self.root / "nepbin"
            nepps.mkdir()
            (nepps / "ps").write_text(
                "#!/bin/sh\n"
                "[ \"$1\" = '-o' ] && [ \"$2\" = 'command=' ] && "
                "[ \"$3\" = '-p' ] && [ \"$4\" = \"$TEST_OLD_PID\" ] || exit 1\n"
                "printf '%s\\n' \"$TEST_PS_COMMAND\"\n", encoding="utf-8")
            (nepps / "ps").chmod(0o700)
            signalen = self.root / "installer-signalen"
            haak = self.root / "installer-haak.sh"
            haak.write_text(
                "kill() {\n"
                "  if [ \"$1\" = '-STOP' ]; then\n"
                "    builtin kill \"$@\" || return\n"
                "    /bin/cp \"$TEST_STAGED_STATUS\" \"$TEST_QUEUE_STATUS\"\n"
                "    /bin/cp \"$TEST_STAGED_JOB\" \"$TEST_QUEUE_JOB\"\n"
                "  else\n"
                "    builtin kill \"$@\" || return\n"
                "  fi\n"
                "  printf '%s\\n' \"$1\" >> \"$TEST_SIGNALS\"\n"
                "}\n", encoding="utf-8")
            installatie_env = {**env, "PATH": f"{nepps}:{env.get('PATH', '')}",
                               "BASH_ENV": str(haak), "TEST_OLD_PID": str(eerste.pid),
                               "TEST_PS_COMMAND": f"{sys.executable} {self.root / 'nep-luisteraar' / 'brug.py'} luister",
                               "TEST_STAGED_STATUS": str(staged_status),
                               "TEST_QUEUE_STATUS": str(status),
                               "TEST_STAGED_JOB": str(staged_job),
                               "TEST_QUEUE_JOB": str(job), "TEST_SIGNALS": str(signalen)}
            installer = subprocess.Popen(["/bin/bash", str(script)],
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         text=True, env=installatie_env)
            self.wacht_tot(lambda: signalen.exists() and "-CONT" in signalen.read_text(),
                           timeout=6)
            self.wacht_op(self.ready)
            self.assertEqual(signalen.read_text().splitlines()[:2], ["-STOP", "-CONT"])
            self.assertNotIn("-INT", signalen.read_text().splitlines())
            self.assertIsNone(eerste.poll(), "oude luisteraar kreeg toch INT")
            self.assertIsNone(installer.poll(), "installer meldde overname tijdens een taak")
        finally:
            if installer is not None and installer.poll() is None:
                installer.terminate()
                installer.communicate(timeout=5)
            for proces in (eerste, reserve):
                if proces is not None and proces.poll() is None:
                    self.stop(proces)

    @unittest.skipUnless(os.name == "posix", "overname vereist POSIX-signalen")
    def test_installer_stopt_niet_als_stop_niet_aankomt(self):
        script, env = self.installatie_kopie()
        eerste = self.luisteraar(env=env)
        reserve = installer = None
        try:
            hartslag = self.basis / "hartslag.json"
            self.wacht_tot(lambda: hartslag.exists() and
                           json.loads(hartslag.read_text()).get("pid") == eerste.pid)
            reserve = self.luisteraar("--wacht-op-slot", env={
                **env, "ANTIGRAVITY_SIDECAR_WEB_PORT": "123"})
            self.wacht_tot(lambda: self.reserve_van(reserve.pid) is not None)
            signalen = self.root / "installer-signalen"
            haak = self.root / "installer-haak.sh"
            # Vertraagde levering nabootsen: STOP wordt wel gevraagd maar komt nooit aan.
            haak.write_text(
                "kill() {\n"
                "  printf '%s\\n' \"$1\" >> \"$TEST_SIGNALS\"\n"
                "  [ \"$1\" = '-STOP' ] && return 0\n"
                "  builtin kill \"$@\"\n"
                "}\n", encoding="utf-8")
            installer = subprocess.Popen(
                ["/bin/bash", str(script)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, env={**env, "BASH_ENV": str(haak), "TEST_SIGNALS": str(signalen)})
            self.wacht_tot(lambda: signalen.exists() and "-CONT" in signalen.read_text(),
                           timeout=8)
            installer.terminate()
            installer.communicate(timeout=5)
            regels = signalen.read_text().splitlines()
            self.assertEqual(regels[:2], ["-STOP", "-CONT"])
            self.assertNotIn("-INT", regels)
            self.assertIsNone(eerste.poll(), "oude luisteraar kreeg INT zonder echte pauze")
        finally:
            if installer is not None and installer.poll() is None:
                installer.terminate()
                installer.communicate(timeout=5)
            for proces in (eerste, reserve):
                if proces is not None and proces.poll() is None:
                    self.stop(proces)

    @unittest.skipUnless(os.name == "posix", "procesgroepen vereisen POSIX")
    def test_stop_procesgroep_signaleert_alleen_niet_opgeruimde_leider(self):
        pidpad = self.root / "kleinkind.pid"
        # De leider stopt meteen op TERM; het kleinkind in dezelfde groep negeert TERM.
        proces = subprocess.Popen(
            ["/bin/sh", "-c", "(trap '' TERM; exec sleep 30) & echo $! > \"$1\"; "
             "trap 'exit 0' TERM; while :; do sleep 0.05; done", "leider", str(pidpad)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=True)
        self.wacht_op(pidpad)
        kleinkind = int(pidpad.read_text())
        echte_killpg = os.killpg
        oproepen = []

        def killpg(groep, sig):
            oproepen.append((sig, proces.returncode))
            return echte_killpg(groep, sig)

        with mock.patch.object(brug.os, "killpg", side_effect=killpg):
            brug._stop_procesgroep(proces)
        self.assertIsNotNone(proces.returncode)
        self.assertIn(signal.SIGKILL, [sig for sig, _ in oproepen])
        self.assertTrue(all(code is None for _, code in oproepen),
                        f"groepssignaal na opruimen van de leider: {oproepen}")
        self.wacht_tot(lambda: not self._leeft(kleinkind))
        oproepen.clear()
        with mock.patch.object(brug.os, "killpg", side_effect=killpg):
            brug._stop_procesgroep(proces)
        self.assertEqual(oproepen, [], "opgeruimd proces kreeg toch een groepssignaal")

    @staticmethod
    def _leeft(pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        stand = subprocess.run(["/bin/ps", "-o", "stat=", "-p", str(pid)],
                               capture_output=True, text=True).stdout.strip()
        return bool(stand) and not stand.startswith("Z")

    @unittest.skipUnless(os.name == "posix", "oude luisteraar gebruikt POSIX-luisterslot")
    def test_installer_wacht_op_bezige_oude_luisteraar_zonder_bron(self):
        script, env = self.installatie_kopie()
        brug.maak_mappen(self.basis)
        bezig = self.basis / "bezig" / "lopende-taak"
        bezig.write_text("nog bezig", encoding="utf-8")
        oude_map = self.root / "oude-luisteraar"
        oude_map.mkdir()
        oude_script = oude_map / "brug.py"
        oude_script.write_text(
            "import fcntl, json, os, time\n"
            "from pathlib import Path\n"
            "basis = Path(os.environ['OVERLEG_BRUG_MAP'])\n"
            "slot = os.open(basis / '.luister.slot', os.O_RDWR | os.O_CREAT, 0o600)\n"
            "fcntl.flock(slot, fcntl.LOCK_EX)\n"
            "hartslag = basis / 'hartslag.json'\n"
            "tijdelijk = basis / '.oude-hartslag.tmp'\n"
            "try:\n"
            "    while True:\n"
            "        tijdelijk.write_text(json.dumps({'pid': os.getpid(), "
            "'laatste_tik': time.time(), 'versie': 1}))\n"
            "        os.replace(tijdelijk, hartslag)\n"
            "        time.sleep(0.1)\n"
            "except KeyboardInterrupt:\n"
            "    pass\n"
            "finally:\n"
            "    hartslag.unlink(missing_ok=True)\n"
            "    tijdelijk.unlink(missing_ok=True)\n"
            "    fcntl.flock(slot, fcntl.LOCK_UN)\n"
            "    os.close(slot)\n", encoding="utf-8")
        oude = subprocess.Popen([sys.executable, str(oude_script), "luister"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, env=env)
        reserve = None
        installer = None
        try:
            hartslag = self.basis / "hartslag.json"
            self.wacht_tot(lambda: hartslag.exists() and
                           json.loads(hartslag.read_text()).get("pid") == oude.pid)
            self.assertNotIn("bron", json.loads(hartslag.read_text()))
            sidecar_env = {**env, "ANTIGRAVITY_SIDECAR_WEB_PORT": "123"}
            reserve = self.luisteraar("--wacht-op-slot", env=sidecar_env)
            self.wacht_tot(lambda: self.reserve_van(reserve.pid) is not None)
            installer = subprocess.Popen(["/bin/bash", str(script)], stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, text=True, env=env)
            manifest = self.home / "config" / "sidecars" / "overleg-brug" / "sidecar.json"
            self.wacht_op(manifest)
            time.sleep(1.2)  # Er is dan minstens één controle met een niet-lege bezig-map geweest.
            self.assertIsNone(oude.poll(), "installer stopte een luisteraar met een lopende taak")
            self.assertIsNone(installer.poll(), "installer meldde overname vóór de taak klaar was")
            self.assertEqual(json.loads(hartslag.read_text())["pid"], oude.pid)
            bezig.unlink()
            uit, fout = installer.communicate(timeout=12)
            self.assertEqual(installer.returncode, 0, fout)
            self.assertIn("Oude luisteraar gestopt; sidecar heeft overgenomen", uit)
            oude.communicate(timeout=5)
            self.assertEqual(oude.returncode, 0)
            self.wacht_tot(lambda: hartslag.exists() and
                           json.loads(hartslag.read_text()).get("pid") == reserve.pid)
        finally:
            bezig.unlink(missing_ok=True)
            if installer is not None and installer.poll() is None:
                installer.kill()
                installer.communicate(timeout=5)
            if oude.poll() is None:
                oude.send_signal(signal.SIGINT)
                try:
                    oude.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    oude.kill()
                    oude.communicate(timeout=5)
            if reserve is not None and reserve.poll() is None:
                self.stop(reserve)

    @unittest.skipUnless(os.name == "posix", "luisterslot vereist POSIX")
    def test_installer_stopt_onbekende_terminalpid_niet(self):
        script, env = self.installatie_kopie()
        brug.maak_mappen(self.basis)
        slot = brug._neem_slot(self.basis)
        onbekend = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        reserve = None
        try:
            brug.schrijf_json(self.basis / "hartslag.json", {
                "pid": onbekend.pid, "starttijd": "test", "laatste_tik": time.time(),
                "versie": brug.VERSIE, "bron": "terminal"})
            sidecar_env = {**env, "ANTIGRAVITY_SIDECAR_WEB_PORT": "123"}
            reserve = self.luisteraar("--wacht-op-slot", env=sidecar_env)
            self.wacht_tot(lambda: self.reserve_van(reserve.pid) is not None)
            uit = subprocess.run(["/bin/bash", str(script)], capture_output=True,
                                 text=True, env=env, timeout=10)
            self.assertEqual(uit.returncode, 0, uit.stderr)
            self.assertIn("Sidecar staat klaar als reserve", uit.stdout)
            self.assertIsNone(onbekend.poll(), "installer stopte een proces dat geen brug.py luister is")
        finally:
            if reserve is not None and reserve.poll() is None:
                self.stop(reserve)
            brug.fcntl.flock(slot, brug.fcntl.LOCK_UN)
            os.close(slot)
            if onbekend.poll() is None:
                onbekend.terminate()
            onbekend.wait(timeout=5)


@unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "installeer_sidecar.sh vereist bash")
class InstallatieTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        for naam in ("installeer_sidecar.sh", "brug.sh", "brug.py"):
            shutil.copy2(HIER / naam, self.repo / naam)
        (self.repo / ".venv" / "bin").mkdir(parents=True)
        (self.repo / ".venv" / "bin" / "python").symlink_to(sys.executable)
        self.home = self.root / "thuis"
        self.home.mkdir()
        self.config = self.home / "config"
        self.env = {**os.environ, "HOME": str(self.home), "USERPROFILE": str(self.home),
                    "ANTIGRAVITY_CONFIG_DIR": str(self.config),
                    "OVERLEG_BRUG_MAP": str(self.home / "brug")}

    def script(self, *args):
        return subprocess.run(["/bin/bash", str(self.repo / "installeer_sidecar.sh"), *args],
                              capture_output=True, text=True, env=self.env, timeout=5)

    @unittest.skipUnless(os.name == "posix", "bestandsrechten vereisen POSIX")
    def test_sidecar_installeren_tonen_en_verwijderen(self):
        toon = self.script("--toon")
        self.assertEqual(toon.returncode, 0, toon.stderr)
        gegevens = json.loads(toon.stdout)
        self.assertEqual(gegevens["command"], "/bin/bash")
        self.assertEqual(gegevens["args"], [str((self.repo / "brug.sh").resolve()),
                                           "--ouder-bewaken", "--wacht-op-slot"])
        self.assertEqual(gegevens["restart_policy"], "always")
        self.assertFalse(self.config.exists())
        self.config.mkdir()
        broer = self.config / "sidecars" / "ander"
        broer.mkdir(parents=True)
        (broer / "bewaar").write_text("blijft")
        eerste = self.script("--niet-wachten")
        self.assertEqual(eerste.returncode, 0, eerste.stderr)
        self.assertIn("Zet 'overleg-brug' aan", eerste.stdout)
        map_pad = self.config / "sidecars" / "overleg-brug"
        manifest = map_pad / "sidecar.json"
        self.assertEqual(json.loads(manifest.read_text()), gegevens)
        self.assertEqual(stat.S_IMODE(map_pad.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(manifest.stat().st_mode), 0o600)
        inhoud = manifest.read_bytes()
        inode = manifest.stat().st_ino
        tweede = self.script("--niet-wachten")
        self.assertEqual(tweede.returncode, 0, tweede.stderr)
        self.assertEqual(manifest.read_bytes(), inhoud)
        self.assertEqual(manifest.stat().st_ino, inode)
        brugmap = Path(self.env["OVERLEG_BRUG_MAP"])
        brug.maak_mappen(brugmap)
        for bron, tekst in (("terminal", "Zet 'overleg-brug' aan"),
                            ("sidecar", "Sidecar draait")):
            brug.schrijf_json(brugmap / "hartslag.json", {
                "pid": os.getpid(), "laatste_tik": time.time(), "versie": 2,
                "bron": bron})
            melding = self.script("--niet-wachten")
            self.assertEqual(melding.returncode, 0, melding.stderr)
            self.assertIn(tekst, melding.stdout)
        brug.schrijf_json(brugmap / "hartslag.json", {
            "pid": os.getpid(), "laatste_tik": time.time(), "versie": 2,
            "bron": "terminal"})
        brug.schrijf_json(brugmap / f"reserve.{os.getpid()}.json", {
            "pid": os.getpid(), "starttijd": "test", "laatste_tik": time.time(),
            "versie": 2, "bron": "sidecar"})
        reserve = self.script("--niet-wachten")
        self.assertEqual(reserve.returncode, 0, reserve.stderr)
        self.assertIn("Sidecar staat klaar als reserve", reserve.stdout)
        weg = self.script("--verwijder")
        self.assertEqual(weg.returncode, 0, weg.stderr)
        self.assertFalse(map_pad.exists())
        self.assertEqual((broer / "bewaar").read_text(), "blijft")

    def test_configmap_en_python_verplicht(self):
        ontbreekt = self.script("--niet-wachten")
        self.assertEqual(ontbreekt.returncode, 2)
        self.assertIn("configmap ontbreekt", ontbreekt.stderr)
        self.assertFalse(self.config.exists())
        self.config.mkdir()
        (self.repo / ".venv" / "bin" / "python").unlink()
        zonder_python = self.script("--niet-wachten")
        self.assertEqual(zonder_python.returncode, 2)
        self.assertIn("Python-omgeving ontbreekt", zonder_python.stderr)


@unittest.skipUnless(os.name == "posix", "luisterslot vereist POSIX")
class LuisterZonderNetwerkTests(unittest.TestCase):
    def test_drie_slechte_metingen_ruimen_hartslag_op(self):
        with tempfile.TemporaryDirectory() as tijdelijk:
            thuis = Path(tijdelijk) / "thuis"
            thuis.mkdir()
            basis = thuis / "brug"
            env = {"HOME": str(thuis), "OVERLEG_BRUG_MAP": str(basis),
                   "ANTIGRAVITY_LS_ADDRESS": "127.0.0.1:1", "ANTIGRAVITY_CSRF_TOKEN": "nep"}
            uitslag = []
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(brug, "toegang", side_effect=["ok", "weg", "weg", "weg"]):
                draad = threading.Thread(target=lambda: uitslag.append(
                    brug.main(["luister", "--toegang-interval", "0.2"])), daemon=True)
                draad.start()
                draad.join(timeout=3)
            self.assertFalse(draad.is_alive())
            self.assertEqual(uitslag, [3])
            self.assertFalse((basis / "hartslag.json").exists())

    def test_ouder_weg_tijdens_reservewachten(self):
        with tempfile.TemporaryDirectory() as tijdelijk:
            thuis = Path(tijdelijk) / "thuis"
            thuis.mkdir()
            basis = thuis / "brug"
            env = {"HOME": str(thuis), "OVERLEG_BRUG_MAP": str(basis),
                   "ANTIGRAVITY_LS_ADDRESS": "127.0.0.1:1", "ANTIGRAVITY_CSRF_TOKEN": "nep"}
            ouder = [111]
            geprobeerd = threading.Event()
            uitslag = []

            def bezet(_basis):
                geprobeerd.set()
                raise brug.SlotBezet("Er draait al een luisteraar")

            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(brug, "toegang", return_value="ok"), \
                    mock.patch.object(brug.os, "getppid", side_effect=lambda: ouder[0]), \
                    mock.patch.object(brug, "_neem_slot", side_effect=bezet):
                draad = threading.Thread(target=lambda: uitslag.append(brug.main([
                    "luister", "--wacht-op-slot", "--ouder-bewaken",
                    "--toegang-interval", "0.2"])), daemon=True)
                draad.start()
                self.assertTrue(geprobeerd.wait(timeout=2))
                self.assertFalse((basis / "hartslag.json").exists())
                ouder[0] = 222
                draad.join(timeout=3)
            self.assertFalse(draad.is_alive())
            self.assertEqual(uitslag, [3])
            self.assertFalse((basis / "hartslag.json").exists())


if __name__ == "__main__":
    unittest.main()
