"""codex.sh met een nep-Codex: invoer, foutcodes en wat er in het dashboard komt.
Draait zonder abonnement en zonder netwerk; alleen waar bash bestaat (macOS en Linux).

    python -m unittest test_codex_sh -v
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HIER = Path(__file__).parent
SCRIPT = HIER / "codex.sh"

STUB = r"""#!/bin/bash
case "$1" in
  --version) echo "codex-cli stub"; exit 0 ;;
  login) echo "Logged in using ChatGPT"; exit 0 ;;
  exec)
    if [ "${2:-}" = "--help" ]; then
      echo "--sandbox --model --cd --output-last-message --skip-git-repo-check --ephemeral --ignore-user-config --config --disable"
      exit 0
    fi
    uit=""
    while [ $# -gt 0 ]; do [ "$1" = "-o" ] && uit="$2"; shift; done
    cat > /dev/null
    [ -n "${STUB_SLAAP:-}" ] && sleep "$STUB_SLAAP"
    [ -n "${STUB_FAAL:-}" ] && { echo "stub faalt" >&2; exit 1; }
    [ -n "${STUB_WIS:-}" ] && rm -rf "$STUB_WIS"/*
    printf '**Klaar.**\n\n1. niets gevonden\n' > "$uit"
    exit 0 ;;
esac
exit 1
"""


@unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "codex.sh is een bash-script")
class CodexSh(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.stub = t / "codex"
        self.stub.write_text(STUB, encoding="utf-8")
        self.stub.chmod(0o755)
        self.runs = t / "runs"
        self.werk = t / "werk"
        self.werk.mkdir()
        self.rapport = t / "uit" / "codex-1-proef.md"
        self.env = {**os.environ, "CODEX_BIN": str(self.stub), "AI_DEBAT": str(HIER),
                    "CODEX_SH_PY": sys.executable, "CODEX_SH_RUNS": str(self.runs), "CODEX_HOME": str(t)}

    def tearDown(self):
        self.tmp.cleanup()

    def draai(self, *args, invoer="Lees na.", **extra):
        return subprocess.run([str(SCRIPT), *args], input=invoer, capture_output=True, text=True,
                              env={**self.env, **extra}, timeout=60)

    def soorten(self):
        naam = (self.rapport.parent / (self.rapport.name + ".ronde")).read_text(encoding="utf-8").strip()
        board = self.runs / naam / "board.jsonl"
        return [json.loads(r) for r in board.read_text(encoding="utf-8").splitlines() if r.strip()]

    def gewoon(self, **extra):
        return self.draai("-C", str(self.werk), "-o", str(self.rapport), "-t", "proef", **extra)

    def test_optie_zonder_waarde_stopt(self):
        # D04: vroeger een oneindige lus.
        for optie in ("-C", "-o", "-t", "-s", "-m", "-e", "--verwerking"):
            r = self.draai(optie)
            self.assertEqual(r.returncode, 2, optie)
            self.assertIn("vraagt een waarde", r.stderr)

    def test_geslaagde_ronde_en_verwerking(self):
        r = self.gewoon()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Klaar", r.stdout)
        self.assertEqual([b["soort"] for b in self.soorten()], ["opdracht", "controle"])
        v = self.draai("--verwerking", str(self.rapport), invoer="1. gelijk, hersteld")
        self.assertEqual(v.returncode, 0, v.stderr)
        self.assertEqual([b["soort"] for b in self.soorten()], ["opdracht", "controle", "verwerking"])

    def test_codex_faalt_geeft_fout_in_dashboard(self):
        r = self.gewoon(STUB_FAAL="1")
        self.assertEqual(r.returncode, 1)
        beurten = self.soorten()
        self.assertEqual([b["soort"] for b in beurten], ["opdracht", "fout"])
        self.assertIn("stub faalt", beurten[1]["tekst"])

    def test_dashboard_faalt_geeft_code_3(self):
        # D05: vroeger alleen een waarschuwing en toch code 0.
        r = self.gewoon(STUB_WIS=str(self.runs))
        self.assertEqual(r.returncode, 3)
        self.assertIn("Klaar", r.stdout)
        self.assertIn("NIET in het dashboard", r.stderr)

    def test_onderbreken_markeert_fout(self):
        # D05: vroeger bleef alleen de opdracht staan.
        p = subprocess.Popen([str(SCRIPT), "-C", str(self.werk), "-o", str(self.rapport), "-t", "proef"],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             env={**self.env, "STUB_SLAAP": "30"}, start_new_session=True)
        p.stdin.write("Lees na.")
        p.stdin.close()
        ronde = self.rapport.parent / (self.rapport.name + ".ronde")
        einde = time.monotonic() + 20
        while not ronde.exists() and time.monotonic() < einde:
            time.sleep(0.1)
        time.sleep(0.5)
        os.killpg(p.pid, signal.SIGTERM)
        self.assertEqual(p.wait(timeout=20), 130)
        p.stdout.close()
        p.stderr.close()
        beurten = self.soorten()
        self.assertEqual([b["soort"] for b in beurten], ["opdracht", "fout"])
        self.assertIn("Onderbroken", beurten[1]["tekst"])

    def test_zonder_ronde_py_weigert(self):
        r = self.gewoon(AI_DEBAT=str(Path(self.tmp.name) / "bestaat-niet"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("ronde.py niet gevonden", r.stderr)


if __name__ == "__main__":
    unittest.main()
