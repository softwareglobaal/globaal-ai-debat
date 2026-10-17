"""Driehoeksoverleg zonder echte Codex- of Gemini-aanroep.

    python -m unittest test_overleg -v
"""

import io
import http.server
import json
import os
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import debat
import brug
import overleg
import ronde


HIER = Path(__file__).parent

CODEX_STUB = """import os
import sys
from pathlib import Path

if not sys.argv[1:] or sys.argv[1] != 'exec':
    sys.exit(4)
args = sys.argv[1:]
uit = Path(args[args.index('-o') + 1])
prompt = sys.stdin.read()
teller = Path(os.environ['STUB_CODEX_TELLER'])
nr = int(teller.read_text() if teller.exists() else '0') + 1
teller.write_text(str(nr))
if nr == 1:
    tekst = 'Codex eerste analyse: controleer de afspraak.'
elif nr == 2 and 'Gemini vult aan' in prompt:
    tekst = 'Gezamenlijke eindconclusie: zet de afspraak vast.'
else:
    sys.exit(5)
uit.write_text(tekst, encoding='utf-8')
"""

GEMINI_STUB = """import json
import os
import sys
from pathlib import Path

if sys.argv[1] != 'new-conversation' or 'Codex eerste analyse' not in sys.argv[-1]:
    sys.exit(6)
cid = 'stub-gesprek'
logs = Path(os.environ['GEMINI_BRAIN_DIR']) / cid / '.system_generated' / 'logs'
logs.mkdir(parents=True)
(logs / 'transcript.jsonl').write_text(json.dumps({
    'type': 'PLANNER_RESPONSE', 'status': 'DONE', 'tool_calls': [],
    'content': 'Gemini vult aan: controleer ook de tweede afspraak.'
}) + '\\n', encoding='utf-8')
print(json.dumps({'response': {'newConversation': {'conversationId': cid}}}))
"""


class Overleg(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.map = Path(self.tmp.name)
        self.werkmap = self.map / "werk"
        self.werkmap.mkdir()
        self.rapport = self.map / "uit" / "rapport.md"
        self.runs = self.map / "runs"
        self.brain = self.map / "brain"
        self.teller = self.map / "codex-teller"
        self.oude_runs = debat.RUNS
        debat.RUNS = self.runs
        self.addCleanup(setattr, debat, "RUNS", self.oude_runs)

        codex_py = self.map / "codex_stub.py"
        gemini_py = self.map / "gemini_stub.py"
        codex_py.write_text(CODEX_STUB, encoding="utf-8")
        gemini_py.write_text(GEMINI_STUB, encoding="utf-8")
        self.codex = self.maak_programma("codex_stub", "STUB_CODEX_SCRIPT", codex_py)
        self.gemini = self.maak_programma("gemini_stub", "STUB_GEMINI_SCRIPT", gemini_py)
        self.env = {**os.environ, "CODEX_BIN": str(self.codex), "CODEX_HOME": str(self.map),
                    "STUB_PYTHON": sys.executable, "STUB_CODEX_SCRIPT": str(codex_py),
                    "STUB_GEMINI_SCRIPT": str(gemini_py), "STUB_CODEX_TELLER": str(self.teller),
                    "GEMINI_BRAIN_DIR": str(self.brain), "AI_DEBAT": str(HIER),
                    "CODEX_SH_PY": sys.executable, "CODEX_SH_RUNS": str(self.runs)}
        for naam in ("ANTIGRAVITY_LS_ADDRESS", "ANTIGRAVITY_CSRF_TOKEN",
                     "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY",
                     "GEMINI_AGENTAPI", "GEMINI_BEWAAR_SESSIE"):
            self.env.pop(naam, None)

    def maak_programma(self, naam, script_variabele, script):
        if os.name == "nt":
            wrapper = self.map / f"{naam}.cmd"
            wrapper.write_text(f'@echo off\n"%STUB_PYTHON%" "%{script_variabele}%" %*\n', encoding="utf-8")
        else:
            wrapper = self.map / f"{naam}.sh"
            wrapper.write_text(f'#!/bin/sh\nexec "$STUB_PYTHON" "${script_variabele}" "$@"\n', encoding="utf-8")
            wrapper.chmod(0o755)
        return wrapper

    @unittest.skipUnless(os.name == "posix", "signalen en procesgroepen vereisen POSIX")
    def test_sigterm_en_sighup_stoppen_lopende_codex(self):
        stub = self.map / "codex_wacht.py"
        stub.write_text(
            "import os, time\nfrom pathlib import Path\n"
            "Path(os.environ['STUB_SIGNAL_PID']).write_text(str(os.getpid()))\n"
            "time.sleep(1.2)\n"
            "Path(os.environ['STUB_SIGNAL_MARKER']).write_text('loopt nog')\n"
            "time.sleep(30)\n", encoding="utf-8")
        for sig in (signal.SIGTERM, signal.SIGHUP):
            with self.subTest(signaal=sig.name):
                pidpad = self.map / f"codex-{sig.name}.pid"
                marker = self.map / f"codex-{sig.name}.marker"
                env = {**self.env, "GEMINI_AGENTAPI": str(self.gemini),
                       "STUB_CODEX_SCRIPT": str(stub),
                       "STUB_SIGNAL_PID": str(pidpad), "STUB_SIGNAL_MARKER": str(marker)}
                proces = subprocess.Popen(
                    [sys.executable, str(HIER / "overleg.py"), "-C", str(self.werkmap),
                     "-o", str(self.rapport), "--runs", str(self.runs), "-b", "1"],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, env=env, start_new_session=True)
                try:
                    proces.stdin.write("Onderzoek de afspraak.\n")
                    proces.stdin.close()
                    proces.stdin = None
                    einde = time.monotonic() + 5
                    while not pidpad.exists() and proces.poll() is None and time.monotonic() < einde:
                        time.sleep(0.02)
                    self.assertTrue(pidpad.exists(), "Codex-stub startte niet")
                    os.kill(proces.pid, sig)
                    _, fout = proces.communicate(timeout=7)
                    self.assertIn(proces.returncode, (130, 143), fout)
                    time.sleep(1.3)
                    self.assertFalse(marker.exists(), "Codex draaide door na het stopsignaal")
                finally:
                    if proces.poll() is None:
                        os.killpg(proces.pid, signal.SIGKILL)
                    proces.communicate(timeout=3)
                    if pidpad.exists():
                        try:
                            os.killpg(int(pidpad.read_text()), signal.SIGKILL)
                        except ProcessLookupError:
                            pass

    @unittest.skipUnless(os.name == "posix", "signalen vereisen POSIX")
    def test_sigterm_gevolgd_door_sighup_onderbreekt_opruiming_niet(self):
        begonnen = self.map / "overleg-begonnen"
        opruiming = self.map / "overleg-opruiming"
        afgerond = self.map / "overleg-opgeruimd"
        driver = self.map / "overleg_dubbel_signaal.py"
        driver.write_text(
            "import sys, time\nfrom pathlib import Path\n"
            f"sys.path.insert(0, {str(HIER)!r})\n"
            "import overleg\n"
            "def nep_overleg(**_):\n"
            f"    Path({str(begonnen)!r}).write_text('begonnen')\n"
            "    try:\n"
            "        time.sleep(30)\n"
            "    finally:\n"
            f"        Path({str(opruiming)!r}).write_text('bezig')\n"
            "        time.sleep(1)\n"
            f"        Path({str(afgerond)!r}).write_text('klaar')\n"
            "overleg.draai_overleg = nep_overleg\n"
            f"sys.exit(overleg.main(['-C', {str(self.werkmap)!r}, "
            f"'-o', {str(self.rapport)!r}]))\n",
            encoding="utf-8")
        proces = subprocess.Popen(
            [sys.executable, str(driver)], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env=self.env, start_new_session=True)
        try:
            proces.stdin.write("Onderzoek de afspraak.\n")
            proces.stdin.close()
            proces.stdin = None
            einde = time.monotonic() + 5
            while not begonnen.exists() and proces.poll() is None and time.monotonic() < einde:
                time.sleep(0.01)
            self.assertTrue(begonnen.exists(), "nep-overleg startte niet")
            os.kill(proces.pid, signal.SIGTERM)
            einde = time.monotonic() + 5
            while not opruiming.exists() and proces.poll() is None and time.monotonic() < einde:
                time.sleep(0.01)
            self.assertTrue(opruiming.exists(), "opruiming begon niet")
            os.kill(proces.pid, signal.SIGHUP)
            _, fout = proces.communicate(timeout=5)
            self.assertEqual(proces.returncode, 130, fout)
            self.assertTrue(afgerond.exists(), "SIGHUP brak de opruiming af")
        finally:
            if proces.poll() is None:
                os.killpg(proces.pid, signal.SIGKILL)
            proces.communicate(timeout=3)

    def python(self, *opties, env=None):
        return subprocess.run(
            [sys.executable, str(HIER / "overleg.py"), "-C", str(self.werkmap),
             "-o", str(self.rapport), "--runs", str(self.runs), *opties],
            input="Onderzoek de afspraak.", capture_output=True, text=True,
            env=env or self.env, timeout=30,
        )

    def beurten(self):
        naam = Path(str(self.rapport) + ".ronde").read_text(encoding="utf-8").strip()
        run_dir = self.runs / naam
        board = [json.loads(regel) for regel in (run_dir / "board.jsonl")
                 .read_text(encoding="utf-8").splitlines()]
        return run_dir, board

    def test_ontbrekende_toegang_stopt_voor_codex_en_ronde(self):
        for adres in (None, " \t"):
            with self.subTest(adres=adres):
                env = self.env.copy()
                if adres is not None:
                    env["ANTIGRAVITY_LS_ADDRESS"] = adres
                uit = self.python(env=env)
                self.assertEqual(uit.returncode, 2, uit.stderr)
                self.assertIn("Terminal van Antigravity: Terminal > New Terminal", uit.stderr)
                self.assertFalse(self.teller.exists(), "Codex werd toch aangeroepen")
                self.assertFalse(self.runs.exists(), "de ronde werd toch aangemaakt")
                self.assertFalse(self.rapport.exists())

    def test_timeout_komt_aan_in_draai_overleg(self):
        for optie in ("-T", "--timeout"):
            with self.subTest(optie=optie):
                with mock.patch.object(overleg, "draai_overleg", return_value=0) as draai:
                    with mock.patch("sys.stdin", io.StringIO("Onderzoek de afspraak.")):
                        code = overleg.main(["-C", str(self.werkmap), "-o", str(self.rapport),
                                            "--runs", str(self.runs), optie, "37"])
                self.assertEqual(code, 0)
                self.assertEqual(draai.call_args.kwargs["timeout"], 37)
        with mock.patch.object(overleg, "draai_overleg", return_value=0) as draai:
            with mock.patch("sys.stdin", io.StringIO("Onderzoek de afspraak.")):
                overleg.main(["-C", str(self.werkmap), "-o", str(self.rapport),
                              "--runs", str(self.runs)])
        self.assertEqual(draai.call_args.kwargs["timeout"], 1200)

    def test_timeout_geldt_voor_beide_beurten(self):
        with mock.patch.dict(os.environ, {"GEMINI_AGENTAPI": str(self.gemini),
                                              "CODEX_HOME": str(self.map)}):
            with mock.patch.object(overleg, "roep_codex_in_map", return_value="Codex antwoord") as codex:
                with mock.patch.object(debat, "roep_gemini", return_value="Gemini slot") as gemini:
                    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                        code = overleg.draai_overleg(self.werkmap, self.rapport, "Test", "Opdracht",
                                                    rondes=1, timeout=37)
        self.assertEqual(code, 0)
        self.assertEqual(codex.call_args.args[-1], 37)
        self.assertEqual(gemini.call_args.args[3], 37)

    def test_ongeldige_timeout_wordt_geweigerd(self):
        for waarde in ("0", "-1", "1.5", "abc"):
            with self.subTest(waarde=waarde):
                fout = io.StringIO()
                with redirect_stderr(fout), self.assertRaises(SystemExit) as stop:
                    overleg.main(["-C", str(self.werkmap), "-o", str(self.rapport),
                                  "--runs", str(self.runs), "-T", waarde])
                self.assertEqual(stop.exception.code, 2)
                self.assertIn("geheel getal groter dan 0", fout.getvalue())
                self.assertFalse(self.teller.exists())

    @unittest.skipIf(os.name == "nt", "cmd.exe knipt een prompt van meerdere regels af in een .cmd-stub; "
                     "agentapi bestaat alleen op macOS (Antigravity)")
    def test_volledige_ronde_met_stub_agentapi(self):
        env = {**self.env, "GEMINI_AGENTAPI": str(self.gemini)}
        uit = self.python("-b", "2", "-T", "37", env=env)
        self.assertEqual(uit.returncode, 0, uit.stderr)
        rapport = self.rapport.read_text(encoding="utf-8")
        self.assertIn("Gezamenlijke Eindconclusie", rapport)
        self.assertIn("zet de afspraak vast", rapport)
        self.assertEqual(self.teller.read_text(), "2")
        naam = Path(str(self.rapport) + ".ronde").read_text(encoding="utf-8").strip()
        board = [json.loads(regel) for regel in (self.runs / naam / "board.jsonl")
                 .read_text(encoding="utf-8").splitlines()]
        self.assertEqual([b["kant"] for b in board], ["claude", "codex", "gemini", "codex"])
        self.assertEqual([b["soort"] for b in board], ["opdracht", "overleg", "overleg", "controle"])
        self.assertIn("Gemini vult aan", board[2]["tekst"])
        self.assertFalse((self.brain / "stub-gesprek").exists())

    def test_modellen_en_denkstand_worden_vastgelegd(self):
        with mock.patch.dict(os.environ, {"GEMINI_AGENTAPI": str(self.gemini),
                                          "CODEX_HOME": str(self.map)}):
            with mock.patch.object(overleg, "roep_codex_in_map", return_value="Codex antwoord") as codex:
                with mock.patch.object(debat, "roep_gemini", return_value="Gemini antwoord") as gemini:
                    with mock.patch.object(debat, "roep_claude", return_value="Claude slot") as claude:
                        with mock.patch("sys.stdin", io.StringIO("Onderzoek de afspraak.")):
                            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                                code = overleg.main([
                                    "-C", str(self.werkmap), "-o", str(self.rapport),
                                    "--runs", str(self.runs), "-b", "3",
                                    "-m", "gpt-5.4", "-e", "xhigh",
                                    "-g", "gemini-4-argon", "-G", "high",
                                    "-c", "claude-opus-4-7", "-E", "max",
                                    "--met-claude",
                                ])
        self.assertEqual(code, 0)
        self.assertEqual(codex.call_args.args[2:5], ("gpt-5.4", "xhigh", 1200))
        self.assertEqual(gemini.call_args.args[2], "gemini-4-argon")
        self.assertEqual(gemini.call_args.kwargs.get("niveau"), "high")
        self.assertEqual(claude.call_args.args[2], "claude-opus-4-7")
        self.assertEqual(claude.call_args.kwargs.get("niveau"), "max")
        rapport = self.rapport.read_text(encoding="utf-8")
        self.assertIn("- Claude: `claude-opus-4-7` (denkstand: `max`)", rapport)
        self.assertIn("- Codex: `gpt-5.4` (denkstand: `xhigh`)", rapport)
        self.assertIn("- Gemini (Antigravity): `Gemini 4 Argon (High)` (`gemini-4-argon`, denkstand: `high`)", rapport)
        naam = Path(str(self.rapport) + ".ronde").read_text(encoding="utf-8").strip()
        onderwerp = json.loads((self.runs / naam / "onderwerp.json").read_text(encoding="utf-8"))
        self.assertEqual(onderwerp["codex_model"], "gpt-5.4")
        self.assertEqual(onderwerp["codex_niveau"], "xhigh")
        self.assertEqual(onderwerp["gemini_model"], "gemini-4-argon")
        self.assertEqual(onderwerp["gemini_niveau"], "high")
        self.assertEqual(onderwerp["gemini_model_enum"], "MODEL_PLACEHOLDER_M417")
        self.assertEqual(onderwerp["claude_model"], "claude-opus-4-7 · max")
        self.assertEqual(onderwerp["claude_niveau"], "max")

    def test_auto_detectie_antigravity_en_gemini_model_mapping(self):
        self.assertEqual(
            debat.gemini_model_info("gemini-4-argon", "high"),
            ("gemini-4-argon", "high", "MODEL_PLACEHOLDER_M417", "Gemini 4 Argon (High)", "pro"),
        )
        self.assertEqual(
            debat.gemini_model_info("flash", "medium"),
            ("gemini-3.8-flash", "medium", "MODEL_PLACEHOLDER_M319", "Gemini 3.8 Flash (Medium)", "flash"),
        )
        ps_tekst = (
            "41164 /Users/test/.local/bin/claude --output-format stream-json --model claude-opus-4-7 --effort max\n"
        )
        with mock.patch.dict(os.environ, {
            "ANTIGRAVITY_LS_ADDRESS": "localhost:53510",
            "ANTIGRAVITY_CSRF_TOKEN": "nep-test-token-123",
        }, clear=True):
            gevonden = debat._antigravity_omgeving()
            self.assertEqual(gevonden, ("localhost:53510", "nep-test-token-123"))
            c_model, c_niveau = debat._claude_standaard(ps_tekst=ps_tekst)
            self.assertEqual((c_model, c_niveau), ("claude-opus-4-7", "max"))

    def test_http_fout_schrijft_geen_serverbody_of_geheim_weg(self):
        fake_body = "nep-sleutel-in-serverbody"
        fout = urllib.error.HTTPError(
            "http://localhost:53510/rpc?token=nep-sleutel-in-url", 403,
            "nep-sleutel-in-reden", {"Authorization": "nep-sleutel-in-header"},
            io.BytesIO(fake_body.encode()),
        )
        env = {"ANTIGRAVITY_LS_ADDRESS": "localhost:53510",
               "ANTIGRAVITY_CSRF_TOKEN": "nep-sleutel-in-omgeving",
               "CODEX_HOME": str(self.map)}
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(debat, "BRAIN_DIR", self.brain):
                with mock.patch.object(overleg, "roep_codex_in_map", return_value="Codex analyse"):
                    with mock.patch.object(debat.urllib.request.OpenerDirector, "open", side_effect=fout):
                        with redirect_stderr(stderr):
                            code = overleg.draai_overleg(self.werkmap, self.rapport, "Test", "Opdracht", rondes=1)
        self.assertEqual(code, 1)
        run_dir, board = self.beurten()
        self.assertEqual(board[-1]["soort"], "fout")
        self.assertIn("Antigravity StartCascade HTTP 403", board[-1]["tekst"])
        tekst = stderr.getvalue() + "\n" + "\n".join(
            p.read_text(encoding="utf-8") for p in run_dir.rglob("*") if p.is_file()
        )
        for geheim in (fake_body, "nep-sleutel-in-url", "nep-sleutel-in-reden",
                       "nep-sleutel-in-header", "nep-sleutel-in-omgeving"):
            self.assertNotIn(geheim, tekst)
        self.assertFalse(self.rapport.exists())

    def test_onverwachte_gemini_fout_wordt_ook_gezuiverd(self):
        env = {"GEMINI_AGENTAPI": str(self.gemini), "CODEX_HOME": str(self.map)}
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(overleg, "roep_codex_in_map", return_value="Codex analyse"):
                with mock.patch.object(debat, "roep_gemini",
                                       side_effect=RuntimeError("Authorization: nep-geheim")):
                    with redirect_stderr(stderr):
                        code = overleg.draai_overleg(self.werkmap, self.rapport, "Test", "Opdracht", rondes=1)
        self.assertEqual(code, 1)
        _, board = self.beurten()
        self.assertIn("Gemini-aanroep mislukt", board[-1]["tekst"])
        self.assertNotIn("nep-geheim", board[-1]["tekst"] + stderr.getvalue())

    def test_onuitvoerbare_gemini_keuze_stopt_voor_eerste_beurt(self):
        env = {**self.env, "GEMINI_AGENTAPI": str(self.gemini)}
        for model, niveau in (("flash_lite", "high"), ("gemini-4-argon", "medium"),
                              ("gemini-3.8-flash", "medium")):
            with self.subTest(model=model, niveau=niveau):
                uit = self.python("-g", model, "-G", niveau, env=env)
                self.assertEqual(uit.returncode, 2, uit.stderr)
                self.assertIn("denkniveau", uit.stderr)
                self.assertFalse(self.teller.exists(), "Codex werd toch aangeroepen")
                self.assertFalse(self.runs.exists(), "de ronde werd toch aangemaakt")
                self.assertFalse(self.rapport.exists())
        self.assertEqual(debat.gemini_model_info("flash_lite", "")[:2],
                         ("gemini-3.8-flash", "low"))
        with self.assertRaisesRegex(ValueError, "vereist denkniveau low"):
            debat.gemini_model_info("flash_lite-high", "")
        uit = self.python("-G", "xhigh", env=env)
        self.assertEqual(uit.returncode, 2, uit.stderr)
        self.assertIn("onbekend Gemini-denkniveau", uit.stderr)
        self.assertFalse(self.runs.exists())

    def test_agentapi_fouttekst_met_sleutel_wordt_niet_bewaard(self):
        geheim = "nep-sleutel-uit-agentapi"
        env = {"GEMINI_AGENTAPI": str(self.gemini), "GEMINI_BRAIN_DIR": str(self.brain),
               "CODEX_HOME": str(self.map)}
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(overleg, "roep_codex_in_map", return_value="Codex analyse"):
                with mock.patch.object(debat, "_draai", return_value=(1, geheim, geheim)):
                    with redirect_stderr(stderr):
                        code = overleg.draai_overleg(self.werkmap, self.rapport, "Test", "Opdracht", rondes=1)
        self.assertEqual(code, 1)
        _, board = self.beurten()
        self.assertIn("agentapi gaf exitcode 1", board[-1]["tekst"])
        self.assertNotIn(geheim, board[-1]["tekst"] + stderr.getvalue())

    def test_rechtstreekse_opruimfout_staat_in_stderr_en_beurt(self):
        geheim = "nep-sleutel-uit-opruimantwoord"
        methodes = []

        def rpc(adres, token, methode, payload, timeout=15.0):
            methodes.append(methode)
            if methode == "StartCascade":
                return {"cascadeId": "stub-gesprek"}
            if methode == "GetCascadeTrajectory":
                return {"trajectory": {"steps": [{
                    "type": "CORTEX_STEP_TYPE_PLANNER_RESPONSE",
                    "status": "CORTEX_STEP_STATUS_DONE",
                    "plannerResponse": {"response": "Gemini antwoord", "toolCalls": []},
                }]}}
            if methode == "DeleteCascadeTrajectory":
                raise RuntimeError(geheim)
            return {}

        env = {"ANTIGRAVITY_LS_ADDRESS": "localhost:53510",
               "ANTIGRAVITY_CSRF_TOKEN": "nep-token", "CODEX_HOME": str(self.map)}
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(debat, "BRAIN_DIR", self.brain):
                with mock.patch.object(overleg, "roep_codex_in_map", return_value="Codex analyse"):
                    with mock.patch.object(debat, "_antigravity_rpc", side_effect=rpc):
                        with redirect_stderr(stderr):
                            code = overleg.draai_overleg(self.werkmap, self.rapport, "Test", "Opdracht", rondes=1)
        self.assertEqual(code, 1)
        self.assertEqual(methodes, ["StartCascade", "SendUserCascadeMessage",
                                   "GetCascadeTrajectory", "DeleteCascadeTrajectory"])
        _, board = self.beurten()
        self.assertIn("DeleteCascadeTrajectory: opruiming mislukt", board[-1]["tekst"])
        self.assertIn("DeleteCascadeTrajectory: opruiming mislukt", stderr.getvalue())
        self.assertNotIn(geheim, board[-1]["tekst"] + stderr.getvalue())

    def test_gemini_deadline_omvat_starten_en_wachten(self):
        klok = [100.0]
        gesprekken = []

        def rpc(adres, token, methode, payload, timeout=15.0):
            gesprekken.append((methode, timeout))
            if methode == "StartCascade":
                klok[0] += 6
                return {"cascadeId": "stub-gesprek"}
            if methode == "SendUserCascadeMessage":
                klok[0] += 3
                return {}
            klok[0] += 0.5
            return {"trajectory": {"steps": [{
                "type": "CORTEX_STEP_TYPE_PLANNER_RESPONSE",
                "status": "CORTEX_STEP_STATUS_DONE",
                "plannerResponse": {"response": "Gemini klaar", "toolCalls": []},
            }]}}

        env = {"ANTIGRAVITY_LS_ADDRESS": "localhost:53510",
               "ANTIGRAVITY_CSRF_TOKEN": "nep-token", "GEMINI_BEWAAR_SESSIE": "1"}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(debat, "BRAIN_DIR", self.brain):
                with mock.patch.object(debat.time, "monotonic", side_effect=lambda: klok[0]):
                    with mock.patch.object(debat, "_antigravity_rpc", side_effect=rpc):
                        tekst = debat.roep_gemini("Systeem", "Prompt", timeout=10)
        self.assertEqual(tekst, "Gemini klaar")
        self.assertEqual(gesprekken, [("StartCascade", 10.0),
                                      ("SendUserCascadeMessage", 4.0),
                                      ("GetCascadeTrajectory", 1.0)])

    def test_agentapi_wachten_krijgt_geen_nieuwe_deadline(self):
        klok = [100.0]

        def start_stub(*args, **kwargs):
            klok[0] += 8
            return 0, json.dumps({"response": {"newConversation": {"conversationId": "stub-gesprek"}}}), ""

        env = {"GEMINI_AGENTAPI": str(self.gemini), "GEMINI_BRAIN_DIR": str(self.brain)}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(debat.time, "monotonic", side_effect=lambda: klok[0]):
                with mock.patch.object(debat.time, "sleep", side_effect=lambda s: klok.__setitem__(0, klok[0] + s)):
                    with mock.patch.object(debat, "_draai", side_effect=start_stub) as draai:
                        with self.assertRaises(debat.GeminiFout) as fout:
                            debat.roep_gemini("Systeem", "Prompt", timeout=10)
        self.assertIn("tijdlimiet", str(fout.exception))
        self.assertEqual(klok[0], 110.0)
        self.assertEqual(draai.call_args.kwargs["deadline"], 110.0)


@unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "overleg.sh vereist bash")
@unittest.skipUnless(os.name == "posix", "procesgroepen vereisen POSIX")
class AntigravityRpcBeveiliging(unittest.TestCase):
    def test_ongeldige_adressen_worden_geweigerd_zonder_verzoek(self):
        for adres in ("example.com:80", "127.0.0.1:80/pad",
                      "gebruiker@localhost:80", "[::1]:80/pad"):
            with self.subTest(adres=adres), \
                    mock.patch.object(debat.urllib.request, "build_opener") as opener:
                with self.assertRaises(debat.GeminiFout) as fout:
                    debat._antigravity_rpc(adres, "nep", "Heartbeat", {})
                self.assertNotIn(adres, str(fout.exception))
                opener.assert_not_called()

    def test_proxy_en_omleiding_kunnen_token_niet_meenemen(self):
        toestand = {"bezoeken": 0, "code": 200, "token": None}

        class NepServer(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                # Eerst de body lezen: een ongelezen body laat de server de verbinding met RST
                # sluiten, en dan faalt de RPC af en toe met "verbinding mislukt".
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                toestand["bezoeken"] += 1
                toestand["token"] = self.headers.get("x-codeium-csrf-token")
                self.send_response(toestand["code"])
                if toestand["code"] == 302:
                    self.send_header("Location", f"http://127.0.0.1:{server.server_port}/omleiding")
                self.send_header("Content-Length", "2" if toestand["code"] == 200 else "0")
                self.end_headers()
                if toestand["code"] == 200:
                    self.wfile.write(b"{}")

            def log_message(self, *args):
                pass

        try:
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), NepServer)
        except PermissionError as exc:
            if os.environ.get("CI"):
                raise
            self.skipTest(f"loopbackpoort geblokkeerd: {exc}")
        draad = threading.Thread(target=server.serve_forever, daemon=True)
        draad.start()
        try:
            adres = f"127.0.0.1:{server.server_port}"
            with mock.patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:1",
                                              "NO_PROXY": "", "no_proxy": ""}):
                self.assertEqual(debat._antigravity_rpc(adres, "nep", "Heartbeat", {}), {})
                self.assertEqual((toestand["bezoeken"], toestand["token"]), (1, "nep"))
                toestand["code"] = 302
                with self.assertRaisesRegex(debat.GeminiFout, "HTTP 302"):
                    debat._antigravity_rpc(adres, "nep", "Heartbeat", {})
                self.assertEqual(toestand["bezoeken"], 2, "RPC volgde de omleiding")
        finally:
            server.shutdown()
            server.server_close()
            draad.join(timeout=2)


class DebatProcesOpruiming(unittest.TestCase):
    def test_keyboardinterrupt_bij_registratie_stopt_kind_en_kleinkind(self):
        with tempfile.TemporaryDirectory() as tijdelijk:
            basis = Path(tijdelijk)
            pidpad = basis / "kleinkind.pid"
            marker = basis / "kleinkind.leeft"
            kleinkind = (
                "import time; from pathlib import Path; "
                f"time.sleep(1.2); Path({str(marker)!r}).write_text('loopt nog'); "
                "time.sleep(30)"
            )
            ouder = (
                "import subprocess, sys, time; "
                f"kind = subprocess.Popen([sys.executable, '-c', {kleinkind!r}]); "
                f"open({str(pidpad)!r}, 'w').write(str(kind.pid)); "
                "time.sleep(30)"
            )
            gestart = {}

            def registreer(proces):
                if proces is None:
                    return
                gestart["proces"] = proces
                einde = time.monotonic() + 5
                while not pidpad.exists() and time.monotonic() < einde:
                    time.sleep(0.02)
                self.assertTrue(pidpad.exists(), "kleinkind startte niet")
                raise KeyboardInterrupt

            try:
                with self.assertRaises(KeyboardInterrupt):
                    debat._draai([sys.executable, "-c", ouder], "", 10, registreer)
                time.sleep(1.3)
                self.assertFalse(marker.exists(), "kleinkind draaide door na KeyboardInterrupt")
            finally:
                proces = gestart.get("proces")
                if proces is not None:
                    try:
                        os.killpg(proces.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    proces.communicate(timeout=3)

    def test_afgescheiden_kleinkind_met_open_uitvoerpijp_blokkeert_niet(self):
        with tempfile.TemporaryDirectory() as tijdelijk:
            pidpad = Path(tijdelijk) / "afgescheiden.pid"
            ouder = (
                "import subprocess, sys, time; "
                "kind = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], "
                "start_new_session=True); "
                f"open({str(pidpad)!r}, 'w').write(str(kind.pid)); "
                "time.sleep(30)"
            )
            gestart = {}
            uitkomst = {}

            def registreer(proces):
                if proces is None:
                    return
                gestart["proces"] = proces
                einde = time.monotonic() + 5
                while not pidpad.exists() and time.monotonic() < einde:
                    time.sleep(0.02)
                self.assertTrue(pidpad.exists(), "afgescheiden kleinkind startte niet")
                raise KeyboardInterrupt

            def draai():
                try:
                    debat._draai([sys.executable, "-c", ouder], "", 10, registreer)
                except BaseException as exc:
                    uitkomst["fout"] = exc

            draad = threading.Thread(target=draai, daemon=True)
            begin = time.monotonic()
            draad.start()
            draad.join(timeout=3)
            bleef_hangen = draad.is_alive()
            duur = time.monotonic() - begin
            try:
                self.assertFalse(bleef_hangen, "communicate bleef op de uitvoerpijp wachten")
                self.assertIsInstance(uitkomst.get("fout"), KeyboardInterrupt)
                self.assertLess(duur, 3)
            finally:
                if pidpad.exists():
                    try:
                        os.kill(int(pidpad.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                proces = gestart.get("proces")
                if proces is not None and proces.poll() is None:
                    os.killpg(proces.pid, signal.SIGKILL)
                draad.join(timeout=3)
                if proces is not None:
                    proces.wait(timeout=3)


class OverlegSh(unittest.TestCase):
    setUp = Overleg.setUp
    maak_programma = Overleg.maak_programma

    def shell(self, *opties, env=None):
        return subprocess.run(["bash", str(HIER / "overleg.sh"), *opties],
                              input="Onderzoek de afspraak.", capture_output=True, text=True,
                              env=env or self.env, timeout=30)

    def test_shell_stopt_ook_bij_zelftest_zonder_toegang(self):
        for opties in (("-C", str(self.werkmap), "-o", str(self.rapport)), ("--zelftest",)):
            with self.subTest(opties=opties):
                uit = self.shell(*opties)
                self.assertEqual(uit.returncode, 2, uit.stderr)
                self.assertIn("Terminal van Antigravity: Terminal > New Terminal", uit.stderr)
                self.assertFalse(self.teller.exists())
                self.assertFalse(self.runs.exists())

    def test_shell_geeft_timeout_door_en_helpt(self):
        hulp = self.shell("--help")
        self.assertEqual(hulp.returncode, 0, hulp.stderr)
        self.assertIn("-T", hulp.stdout)
        self.assertIn("Terminal van Antigravity", hulp.stdout)
        args_bestand = self.map / "python-args"
        fake_python = self.map / "fake-python.sh"
        fake_python.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$STUB_PYTHON_ARGS"\n', encoding="utf-8")
        fake_python.chmod(0o755)
        env = {**self.env, "GEMINI_AGENTAPI": str(self.gemini),
               "CODEX_SH_PY": str(fake_python), "STUB_PYTHON_ARGS": str(args_bestand)}
        uit = self.shell("-C", str(self.werkmap), "-o", str(self.rapport), "-T", "47", env=env)
        self.assertEqual(uit.returncode, 0, uit.stderr)
        args = args_bestand.read_text(encoding="utf-8").splitlines()
        self.assertEqual(args[args.index("-T") + 1], "47")
        self.assertEqual(args[args.index("--runs") + 1], str(self.runs))

    def test_shell_weigert_ongeldige_timeout(self):
        env = {**self.env, "GEMINI_AGENTAPI": str(self.gemini)}
        uit = self.shell("-C", str(self.werkmap), "-o", str(self.rapport), "-T", "0", env=env)
        self.assertEqual(uit.returncode, 2, uit.stderr)
        self.assertIn("geheel getal groter dan 0", uit.stderr)
        self.assertFalse(self.teller.exists())

    def test_shell_behoudt_claude_model_en_eist_agentapi_alleen_bij_terugval(self):
        args_bestand = self.map / "python-args"
        fake_python = self.map / "fake-python.sh"
        fake_python.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$STUB_PYTHON_ARGS"\n',
                               encoding="utf-8")
        fake_python.chmod(0o755)
        env = {**self.env, "ANTIGRAVITY_LS_ADDRESS": "localhost:53510",
               "ANTIGRAVITY_CSRF_TOKEN": "nep-token", "CLAUDE_MODEL": "claude-opus-test",
               "CODEX_SH_PY": str(fake_python), "STUB_PYTHON_ARGS": str(args_bestand)}
        env.pop("GEMINI_AGENTAPI", None)
        env.pop("GEMINI_BRAIN_DIR", None)
        uit = self.shell("-C", str(self.werkmap), "-o", str(self.rapport), env=env)
        self.assertEqual(uit.returncode, 0, uit.stderr)
        args = args_bestand.read_text(encoding="utf-8").splitlines()
        self.assertEqual(args[args.index("-c") + 1], "claude-opus-test")
        self.assertNotIn("-G", args)

        env["GEMINI_AGENTAPI"] = str(self.map / "niet-bestaande-agentapi")
        uit = self.shell("-C", str(self.werkmap), "-o", str(self.rapport), env=env)
        self.assertEqual(uit.returncode, 2, uit.stderr)
        self.assertIn("Gemini agentapi niet gevonden", uit.stderr)


@unittest.skipUnless(os.name == "posix", "overleg.sh en levende pid vereisen POSIX")
class DoorsturenViaBrug(unittest.TestCase):
    RAPPORT = "RAPPORT VIA BRUG\n"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "thuis"
        self.home.mkdir()
        self.basis = self.home / "brug"
        self.werkmap = self.home / "werk"
        self.werkmap.mkdir()
        self.rapport = self.home / "uit" / "rapport.md"
        self.runs = self.home / "runs"
        self.env = {**os.environ, "HOME": str(self.home), "USERPROFILE": str(self.home),
                    "OVERLEG_BRUG_MAP": str(self.basis), "AI_DEBAT": str(HIER),
                    "CODEX_SH_PY": sys.executable, "CODEX_SH_RUNS": str(self.runs)}
        for naam in ("ANTIGRAVITY_LS_ADDRESS", "ANTIGRAVITY_CSRF_TOKEN",
                     "GEMINI_AGENTAPI", "GEMINI_BRAIN_DIR"):
            self.env.pop(naam, None)
        self.jobs = []
        self.stub_fout = None
        self.stophartslag = threading.Event()
        self.draad = None
        oude_runs = debat.RUNS
        debat.RUNS = self.runs
        self.addCleanup(setattr, debat, "RUNS", oude_runs)
        self.addCleanup(self.stop_stub)

    def start_stub(self):
        brug.maak_mappen(self.basis)

        def loop():
            try:
                while not self.stophartslag.is_set():
                    brug.schrijf_json(self.basis / "hartslag.json", {
                        "pid": os.getpid(), "starttijd": "2026-10-17T12:00:00Z",
                        "laatste_tik": time.time(), "versie": 2, "bron": "sidecar"})
                    taak_id = brug.claim_oudste(self.basis)
                    if taak_id:
                        jobpad = self.basis / "bezig" / f"{taak_id}.json"
                        gegevens = json.loads(jobpad.read_text(encoding="utf-8"))
                        self.jobs.append(gegevens)
                        rapport = Path(gegevens["rapport"])
                        rapport.parent.mkdir(parents=True, exist_ok=True)
                        rapport.write_text(self.RAPPORT, encoding="utf-8")
                        naam = ronde.nieuw(gegevens["titel"], gegevens["opdracht"],
                                          project=gegevens["werkmap"], rapport=str(rapport),
                                          naambestand=str(rapport) + ".ronde")
                        ronde.voeg_toe(ronde.run_pad(naam), "codex", "controle", self.RAPPORT)
                        statuspad = brug._statuspad(self.basis / "bezig", taak_id)
                        brug.schrijf_json(statuspad, brug._status(
                            taak_id, "klaar", exitcode=0, rapport=str(rapport)))
                        os.replace(jobpad, self.basis / "klaar" / jobpad.name)
                        os.replace(statuspad, brug._statuspad(self.basis / "klaar", taak_id))
                    self.stophartslag.wait(0.05)
            except Exception as exc:
                self.stub_fout = exc

        self.draad = threading.Thread(target=loop, daemon=True)
        self.draad.start()
        einde = time.monotonic() + 3
        while not brug.brug_leeft(self.basis):
            self.assertLess(time.monotonic(), einde, "nep-brug startte niet")
            time.sleep(0.01)

    def stop_stub(self):
        self.stophartslag.set()
        if self.draad:
            self.draad.join(timeout=2)

    def shell(self, *args, opdracht="Onderzoek de afspraak.\n"):
        return subprocess.run(["/bin/bash", str(HIER / "overleg.sh"), *args],
                              input=opdracht, capture_output=True, text=True,
                              env=self.env, timeout=10)

    def python(self, *args, opdracht="Onderzoek de afspraak.\n"):
        uit, fout = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, self.env, clear=True), \
                mock.patch("sys.stdin", io.StringIO(opdracht)), \
                redirect_stdout(uit), redirect_stderr(fout):
            code = overleg.main(["-C", str(self.werkmap), "-o", str(self.rapport), *args])
        return code, uit.getvalue(), fout.getvalue()

    def controleer_job(self, titel, opdracht, beurten, model, timeout):
        self.assertIsNone(self.stub_fout)
        self.assertEqual(len(self.jobs), 1)
        job = self.jobs[0]
        self.assertEqual(job["werkmap"], str(self.werkmap.resolve()))
        self.assertEqual(job["titel"], titel)
        self.assertEqual(job["opdracht"], opdracht)
        self.assertEqual(job["opties"]["b"], beurten)
        self.assertEqual(job["opties"]["g"], model)
        self.assertEqual(job["opties"]["T"], timeout)

    def test_shell_stuurt_precies_een_opdracht_door(self):
        self.start_stub()
        opdracht = "Onderzoek deze afspraak.\n"
        uit = self.shell("-C", str(self.werkmap), "-o", str(self.rapport),
                         "-t", "Brugcontrole", "-b", "3", "-g", "gemini-3.8-flash",
                         "-T", "30", opdracht=opdracht)
        self.assertEqual(uit.returncode, 0, uit.stderr)
        self.assertIn(self.RAPPORT, uit.stdout)
        self.controleer_job("Brugcontrole", opdracht, 3, "gemini-3.8-flash", 30)

    def test_python_stuurt_precies_een_opdracht_door(self):
        self.start_stub()
        code, uit, fout = self.python("-t", "Pythonbrug", "-b", "2",
                                     "-g", "gemini-3.8-flash", "-T", "30")
        self.assertEqual(code, 0, fout)
        self.assertIn(self.RAPPORT, uit)
        self.controleer_job("Pythonbrug", "Onderzoek de afspraak.", 2,
                            "gemini-3.8-flash", 30)

    def test_zonder_hartslag_en_met_verlopen_hartslag_geen_wachtrij(self):
        for verlopen in (False, True):
            with self.subTest(verlopen=verlopen):
                if verlopen:
                    brug.maak_mappen(self.basis)
                    brug.schrijf_json(self.basis / "hartslag.json", {
                        "pid": os.getpid(), "starttijd": "2026-10-17T12:00:00Z",
                        "laatste_tik": time.time() - 61, "versie": 1})
                uit = self.shell("-C", str(self.werkmap), "-o", str(self.rapport),
                                 "-t", "Geen brug", "-T", "30")
                self.assertEqual(uit.returncode, 2)
                self.assertIn("Gemini-toegang ontbreekt", uit.stderr)
                code, _, fout = self.python("-t", "Geen brug", "-T", "30")
                self.assertEqual(code, 2)
                self.assertIn("Gemini-toegang ontbreekt", fout)
                wachtrij = self.basis / "wachtrij"
                self.assertFalse(list(wachtrij.glob("*.json")) if wachtrij.exists() else [])

    def test_shell_zelftest_via_brug_en_verwerking(self):
        self.start_stub()
        uit = self.shell("--zelftest")
        self.assertEqual(uit.returncode, 0, uit.stderr)
        self.assertIn("zelftest geslaagd", uit.stdout)
        self.assertIsNone(self.stub_fout)
        self.assertEqual(len(self.jobs), 1)
        naam = next(self.runs.iterdir()).name
        board = [json.loads(regel) for regel in (self.runs / naam / "board.jsonl")
                 .read_text(encoding="utf-8").splitlines()]
        self.assertEqual([beurt["soort"] for beurt in board],
                         ["opdracht", "controle", "verwerking"])


if __name__ == "__main__":
    unittest.main()
