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
        self.env.pop("ANTIGRAVITY_LS_ADDRESS", None)
        self.env.pop("GEMINI_AGENTAPI", None)

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


if __name__ == "__main__":
    unittest.main()

