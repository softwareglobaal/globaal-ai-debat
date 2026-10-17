"""Driehoeksoverleg zonder echte Codex- of Gemini-aanroep.

    python -m unittest test_overleg -v
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import debat
import overleg


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
                    with mock.patch.object(debat.urllib.request, "urlopen", side_effect=fout):
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


if __name__ == "__main__":
    unittest.main()
