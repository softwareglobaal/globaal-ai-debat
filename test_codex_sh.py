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
    [ -n "${STUB_GEROEPEN:-}" ] && touch "$STUB_GEROEPEN"
    [ -n "${STUB_NEGEER_TERM:-}" ] && trap '' TERM
    if [ -n "${STUB_SLAAP:-}" ]; then
      sleep "$STUB_SLAAP" &
      echo "$$ $!" > "$STUB_PIDS"
      wait $!
    fi
    [ -n "${STUB_WIS:-}" ] && rm -rf "$STUB_WIS"/*
    [ -n "${STUB_FAAL:-}" ] && { echo "stub faalt" >&2; exit 1; }
    printf '**Klaar.**\n\n1. niets gevonden\n' > "$uit"
    exit 0 ;;
esac
exit 1
"""

# Python voor ronde.py, maar na de gekozen stap ("nieuw" of "controle") blijft hij hangen; zo valt een signaal
# precies tijdens het aanmaken van de ronde of het wegschrijven van het antwoord.
TRAAG_PY = r"""#!/bin/bash
"$ECHTE_PY" "$@"
rc=$?
case " $* " in
  *" $TRAAG_BIJ "*) touch "$TRAAG_TEKEN"; sleep 3 ;;
esac
exit $rc
"""


def leeft(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # Een zombie (gestopt maar nog niet opgehaald) telt niet als levend.
    uit = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(uit) and not uit.startswith("Z")


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
        self.pids = t / "pids"
        self.geroepen = t / "geroepen"
        self.teken = t / "teken"
        self.traag = t / "traag-python"
        self.traag.write_text(TRAAG_PY, encoding="utf-8")
        self.traag.chmod(0o755)
        self.env = {**os.environ, "CODEX_BIN": str(self.stub), "AI_DEBAT": str(HIER),
                    "CODEX_SH_PY": sys.executable, "CODEX_SH_RUNS": str(self.runs), "CODEX_HOME": str(t),
                    "STUB_PIDS": str(self.pids), "STUB_GEROEPEN": str(self.geroepen),
                    "ECHTE_PY": sys.executable, "TRAAG_TEKEN": str(self.teken)}

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

    def start(self, **extra):
        p = subprocess.Popen([str(SCRIPT), "-C", str(self.werk), "-o", str(self.rapport), "-t", "proef"],
                             stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True,
                             env={**self.env, **extra}, start_new_session=True)
        p.stdin.write("Lees na.")
        p.stdin.close()
        self.addCleanup(lambda: p.poll() is None and os.killpg(p.pid, signal.SIGKILL))
        return p

    def wacht_op(self, pad, s=20):
        einde = time.monotonic() + s
        while not pad.exists():
            self.assertLess(time.monotonic(), einde, f"{pad} kwam er niet")
            time.sleep(0.05)

    def test_onderbreken_markeert_fout(self):
        # D05: vroeger bleef alleen de opdracht staan. Hier krijgt de hele procesgroep van het script het signaal.
        p = self.start(STUB_SLAAP="30")
        self.wacht_op(self.pids)
        os.killpg(p.pid, signal.SIGTERM)
        self.assertEqual(p.wait(timeout=20), 130)
        beurten = self.soorten()
        self.assertEqual([b["soort"] for b in beurten], ["opdracht", "fout"])
        self.assertIn("Onderbroken", beurten[1]["tekst"])

    def test_signaal_aan_script_stopt_codex_en_kinderen(self):
        # D10: alleen het script krijgt het signaal; de val moet Codex en wat Codex startte zelf stoppen.
        p = self.start(STUB_SLAAP="30")
        self.wacht_op(self.pids)
        codex_pids = [int(x) for x in self.pids.read_text().split()]
        os.kill(p.pid, signal.SIGTERM)
        self.assertEqual(p.wait(timeout=10), 130)
        einde = time.monotonic() + 5
        while any(leeft(x) for x in codex_pids) and time.monotonic() < einde:
            time.sleep(0.1)
        self.assertFalse([x for x in codex_pids if leeft(x)], "Codex of zijn kind draait nog")
        self.assertEqual([b["soort"] for b in self.soorten()], ["opdracht", "fout"])

    def test_signaal_stopt_codex_ook_via_python_wrapper(self):
        # D14: is de gekozen python een shellwrapper (pyenv, asdf), dan is $! de wrapper en niet de groep van Codex.
        p = self.start(STUB_SLAAP="30", CODEX_SH_PY=str(self.traag), TRAAG_BIJ="nooit")
        self.wacht_op(self.pids)
        codex_pids = [int(x) for x in self.pids.read_text().split()]
        os.kill(p.pid, signal.SIGTERM)
        self.assertEqual(p.wait(timeout=10), 130)
        einde = time.monotonic() + 5
        while any(leeft(x) for x in codex_pids) and time.monotonic() < einde:
            time.sleep(0.1)
        self.assertFalse([x for x in codex_pids if leeft(x)], "Codex draait nog na een signaal via de wrapper")
        self.assertEqual([b["soort"] for b in self.soorten()], ["opdracht", "fout"])

    def test_gepauzeerde_starter_start_codex_niet_meer(self):
        # D18: de starter (python achter een wrapper) hangt nog voor hij zijn groep meldt; de val geeft na twee
        # seconden op. Daarna mag hij Codex nooit meer starten.
        p = self.start(STUB_SLAAP="30", CODEX_SH_PY=str(self.traag), TRAAG_BIJ="nooit",
                       CODEX_SH_TEST_STARTER_PAUZE="4")
        self.wacht_op(self.rapport.parent / (self.rapport.name + ".ronde"))
        time.sleep(0.5)
        os.kill(p.pid, signal.SIGTERM)
        self.assertEqual(p.wait(timeout=15), 130)
        time.sleep(6)  # ruim na het einde van de pauze van de starter
        self.assertFalse(self.geroepen.exists(), "de starter startte Codex na de onderbreking toch nog")
        self.assertEqual([b["soort"] for b in self.soorten()], ["opdracht", "fout"])

    def test_kind_dat_term_negeert_wordt_alsnog_gestopt(self):
        # D19: TERM volstaat niet altijd; na drie seconden volgt KILL voor de hele groep.
        p = self.start(STUB_SLAAP="30", STUB_NEGEER_TERM="1")
        self.wacht_op(self.pids)
        codex_pids = [int(x) for x in self.pids.read_text().split()]
        begin = time.monotonic()
        os.kill(p.pid, signal.SIGTERM)
        self.assertEqual(p.wait(timeout=15), 130)
        einde = time.monotonic() + 5
        while any(leeft(x) for x in codex_pids) and time.monotonic() < einde:
            time.sleep(0.1)
        self.assertFalse([x for x in codex_pids if leeft(x)], "een kind dat TERM negeert, draait nog")
        self.assertLess(time.monotonic() - begin, 10)

    def test_signaal_tijdens_aanmaken_ronde(self):
        # D10: het signaal valt terwijl de ronde wordt aangemaakt, voor codex.sh haar naam kent.
        p = self.start(CODEX_SH_PY=str(self.traag), TRAAG_BIJ="nieuw")
        self.wacht_op(self.teken)
        os.kill(p.pid, signal.SIGTERM)
        self.assertEqual(p.wait(timeout=15), 130)
        self.assertEqual([b["soort"] for b in self.soorten()], ["opdracht", "fout"])
        self.assertFalse(self.geroepen.exists(), "Codex werd toch nog gestart")

    def test_signaal_na_antwoord_geen_tweede_uitkomst(self):
        # D11: het signaal valt net nadat het antwoord is weggeschreven; er mag geen FOUT bij komen.
        p = self.start(CODEX_SH_PY=str(self.traag), TRAAG_BIJ="controle")
        self.wacht_op(self.teken)
        os.kill(p.pid, signal.SIGTERM)
        self.assertEqual(p.wait(timeout=15), 130)
        self.assertEqual([b["soort"] for b in self.soorten()], ["opdracht", "controle"])

    def test_codex_faalt_en_dashboard_faalt_geeft_code_3(self):
        # D11: ook de fouttak kijkt na of haar beurt in het dashboard kwam.
        r = self.gewoon(STUB_FAAL="1", STUB_WIS=str(self.runs))
        self.assertEqual(r.returncode, 3)
        self.assertIn("ook de fout staat NIET in het dashboard", r.stderr)

    def test_zonder_ronde_py_weigert(self):
        r = self.gewoon(AI_DEBAT=str(Path(self.tmp.name) / "bestaat-niet"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("ronde.py niet gevonden", r.stderr)


if __name__ == "__main__":
    unittest.main()
