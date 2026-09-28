"""Webinterface voor het debat tussen Claude en ChatGPT.

Start met: python web.py   (of start.cmd)
Daarna: http://127.0.0.1:8099

Draait bewust alleen op loopback. De twee abonnementslogins staan op deze
machine, dus de app hoort hier te draaien en niet op de VM.
"""

import json
import os
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, Response

import debat
import opdracht
import verkenner

app = Flask(__name__)

BASIS = debat.BASIS
RUNS = debat.RUNS
ONDERWERPEN = BASIS / "onderwerpen"

LOCK = threading.Lock()
STAAT = {
    "actief": False,
    "run": None,
    "onderwerp": None,
    "beurten": [],
    "totaal": 0,
    "bezig_met": None,
    "fout": None,
    "stop_gevraagd": False,
    "modus": "debat",
    "werkmap": None,
    "tak": None,
}
INJECTIES = []

# Het kindproces van de lopende beurt, zodat Nu stoppen het kan afbreken.
HUIDIG = {"proc": None}

BRIEFING = {"bezig": False, "fout": None, "resultaat": None}

# Waar de mapkiezer begint. Instelbaar met AI_DEBAT_STARTMAP; anders ~/Claude als die
# bestaat, en anders de persoonlijke map.
def _startmap() -> Path:
    eigen = os.environ.get("AI_DEBAT_STARTMAP", "").strip()
    if eigen and Path(eigen).is_dir():
        return Path(eigen)
    claude = Path.home() / "Claude"
    return claude if claude.is_dir() else Path.home()


STARTMAP = _startmap()
MODELLEN = BASIS / "modellen.json"

POORT = 8099
EIGEN_HOSTS = {f"127.0.0.1:{POORT}", f"localhost:{POORT}"}


@app.before_request
def alleen_eigen_pagina():
    """Loopback is geen afscherming: elke website die je open hebt kan naar
    127.0.0.1 posten. Daarom moet een schrijvend verzoek echte JSON zijn (dat
    dwingt bij een vreemde site een CORS-preflight af, die wij niet beantwoorden)
    en van onze eigen pagina komen. De Host-controle houdt DNS-rebinding tegen."""
    if request.host not in EIGEN_HOSTS:
        return jsonify({"fout": "onbekende host"}), 403
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return None
    herkomst = request.headers.get("Origin")
    if herkomst is not None and herkomst.split("://", 1)[-1] not in EIGEN_HOSTS:
        return jsonify({"fout": "verzoek van een andere website geweigerd"}), 403
    if not request.is_json:
        return jsonify({"fout": "alleen application/json"}), 415
    return None


def zet(**velden):
    with LOCK:
        STAAT.update(velden)


def registreer_proces(proc):
    with LOCK:
        HUIDIG["proc"] = proc


def voeg_beurt_toe(beurt, run_dir):
    with LOCK:
        STAAT["beurten"].append(beurt)
        kopie = list(STAAT["beurten"])
        onderwerp = STAAT["onderwerp"]
    with (run_dir / "board.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(beurt, ensure_ascii=False) + "\n")
    debat.schrijf_transcript(run_dir, onderwerp, kopie)


def draai(onderwerp, config):
    """Het debat zelf. Draait in een aparte thread zodat de pagina blijft werken."""
    run_dir = RUNS / datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "onderwerp.json").write_text(
        json.dumps(onderwerp, ensure_ascii=False, indent=2), encoding="utf-8")

    zet(actief=True, run=run_dir.name, onderwerp=onderwerp, beurten=[],
        totaal=config["beurten"], fout=None, stop_gevraagd=False, bezig_met=None,
        modus="debat", werkmap=None, tak=None)

    systeem = debat.HUISREGELS.format(max_woorden=config["max_woorden"])
    kanten = {
        "claude": {"rol": onderwerp["claude"], "roep": debat.roep_claude, "model": config["claude_model"]},
        "codex": {"rol": onderwerp["codex"], "roep": debat.roep_codex, "model": config["codex_model"]},
    }
    beurt_aan = config["start"]

    try:
        for nr in range(1, config["beurten"] + 1):
            with LOCK:
                if STAAT["stop_gevraagd"]:
                    break
                geschiedenis = list(STAAT["beurten"])

            kant = kanten[beurt_aan]
            label = kant["rol"]["naam"]
            zet(bezig_met=label)

            prompt = debat.bouw_prompt(onderwerp, kant["rol"], geschiedenis, config["max_woorden"])
            begin = time.time()
            tekst = kant["roep"](systeem, prompt, kant["model"], config["timeout"],
                                 registreer_proces)
            with LOCK:
                afgebroken = STAAT["stop_gevraagd"]
            if afgebroken:
                break
            if not tekst:
                raise RuntimeError(f"{label} gaf een leeg antwoord")

            voeg_beurt_toe({
                "nr": nr,
                "spreker": label,
                "kant": beurt_aan,
                "model": kant["model"] or "standaard",
                "tijd": datetime.now().isoformat(timespec="seconds"),
                "duur_s": round(time.time() - begin, 1),
                "tekst": tekst,
            }, run_dir)

            # Moderatorberichten die jij intussen hebt ingestuurd.
            with LOCK:
                wachtend = list(INJECTIES)
                INJECTIES.clear()
            for tekst_mod in wachtend:
                voeg_beurt_toe({
                    "nr": nr,
                    "spreker": "MODERATOR",
                    "kant": "mens",
                    "model": "mens",
                    "tijd": datetime.now().isoformat(timespec="seconds"),
                    "duur_s": 0.0,
                    "tekst": tekst_mod,
                }, run_dir)

            beurt_aan = "codex" if beurt_aan == "claude" else "claude"
    except Exception as e:
        # Een afgeschoten proces geeft een exitcode-fout; dat is geen storing.
        with LOCK:
            door_gebruiker = STAAT["stop_gevraagd"]
        if not door_gebruiker:
            zet(fout=str(e)[:800])
    finally:
        registreer_proces(None)
        zet(actief=False, bezig_met=None)


def draai_opdracht(onderwerp, config):
    """Uitvoerder schrijft, reviewer valt aan, uitvoerder herziet. In een worktree."""
    run_dir = RUNS / datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "onderwerp.json").write_text(
        json.dumps(onderwerp, ensure_ascii=False, indent=2), encoding="utf-8")

    zet(actief=True, run=run_dir.name, onderwerp=onderwerp, beurten=[],
        totaal=config["rondes"] * 2, fout=None, stop_gevraagd=False,
        bezig_met=None, modus="opdracht", werkmap=None, tak=None)

    nr = 0
    try:
        werkmap, tak = opdracht.maak_worktree(Path(onderwerp["repo"]))
        zet(werkmap=str(werkmap), tak=tak)

        review = ""
        for ronde in range(1, config["rondes"] + 1):
            with LOCK:
                if STAAT["stop_gevraagd"]:
                    break

            # De uitvoerder schrijft of herziet.
            zet(bezig_met=f"UITVOERDER (ronde {ronde})")
            begin = time.time()
            verslag = opdracht.roep_uitvoerder(
                opdracht.UITVOERDER.format(woorden=config["max_woorden"]),
                opdracht.uitvoer_prompt(onderwerp["opdracht"], review, ronde),
                config["claude_model"], config["timeout"], werkmap,
                config["bash"], registreer_proces)
            with LOCK:
                if STAAT["stop_gevraagd"]:
                    break
            verschil = opdracht.diff_van(werkmap)
            nr += 1
            voeg_beurt_toe({
                "nr": nr, "spreker": f"UITVOERDER (Claude, ronde {ronde})",
                "kant": "claude", "soort": "uitvoering",
                "model": config["claude_model"],
                "tijd": datetime.now().isoformat(timespec="seconds"),
                "duur_s": round(time.time() - begin, 1),
                "tekst": verslag,
                "diff": verschil["diff"],
                "bestanden": {k: verschil[k] for k in ("toegevoegd", "gewijzigd", "verwijderd")},
            }, run_dir)

            if not verschil["diff"].strip():
                zet(fout="de uitvoerder heeft niets gewijzigd, run gestopt")
                break

            # De reviewer beoordeelt.
            zet(bezig_met=f"REVIEWER (ronde {ronde})")
            begin = time.time()
            review = opdracht.roep_reviewer(
                opdracht.REVIEWER.format(woorden=config["max_woorden"]),
                opdracht.review_prompt(onderwerp["opdracht"], verslag, verschil, 60000),
                config["codex_model"], config["timeout"], werkmap, registreer_proces)
            with LOCK:
                if STAAT["stop_gevraagd"]:
                    break
            nr += 1
            voeg_beurt_toe({
                "nr": nr, "spreker": f"REVIEWER (ChatGPT, ronde {ronde})",
                "kant": "codex", "soort": "review",
                "model": config["codex_model"] or "standaard",
                "tijd": datetime.now().isoformat(timespec="seconds"),
                "duur_s": round(time.time() - begin, 1),
                "tekst": review,
            }, run_dir)
    except Exception as e:
        with LOCK:
            door_gebruiker = STAAT["stop_gevraagd"]
        if not door_gebruiker:
            zet(fout=str(e)[:800])
    finally:
        registreer_proces(None)
        zet(actief=False, bezig_met=None)


@app.post("/api/opdracht")
def api_opdracht():
    with LOCK:
        if STAAT["actief"]:
            return jsonify({"fout": "er loopt al iets"}), 409
    gegevens = request.get_json(force=True)
    onderwerp = gegevens["onderwerp"]
    if not opdracht.is_repo(Path(onderwerp.get("repo", ""))):
        return jsonify({"fout": "de gekozen map is geen git-repo"}), 400
    config = {
        "rondes": max(1, min(6, int(gegevens.get("rondes", 2)))),
        "max_woorden": max(50, min(800, int(gegevens.get("max_woorden", 300)))),
        "claude_model": gegevens.get("claude_model", "sonnet"),
        "codex_model": gegevens.get("codex_model", ""),
        "bash": bool(gegevens.get("bash", False)),
        "timeout": 1800,
    }
    threading.Thread(target=draai_opdracht, args=(onderwerp, config), daemon=True).start()
    return jsonify({"ok": True})


@app.post("/api/start")
def api_start():
    with LOCK:
        if STAAT["actief"]:
            return jsonify({"fout": "er loopt al een debat"}), 409
    gegevens = request.get_json(force=True)
    onderwerp = gegevens["onderwerp"]
    config = {
        "beurten": max(1, min(60, int(gegevens.get("beurten", 10)))),
        "max_woorden": max(50, min(800, int(gegevens.get("max_woorden", 250)))),
        "claude_model": gegevens.get("claude_model", "sonnet"),
        "codex_model": gegevens.get("codex_model", ""),
        "start": gegevens.get("start", "claude"),
        "timeout": 300,
    }
    with LOCK:
        INJECTIES.clear()
    threading.Thread(target=draai, args=(onderwerp, config), daemon=True).start()
    return jsonify({"ok": True})


@app.post("/api/stop")
def api_stop():
    """Breekt de lopende beurt direct af. Die halve beurt gaat verloren."""
    zet(stop_gevraagd=True)
    with LOCK:
        proc = HUIDIG["proc"]
    debat.stop_proces(proc)
    return jsonify({"ok": True})


@app.post("/api/injectie")
def api_injectie():
    tekst = (request.get_json(force=True).get("tekst") or "").strip()
    if not tekst:
        return jsonify({"fout": "leeg"}), 400
    with LOCK:
        INJECTIES.append(tekst)
        wachtrij = len(INJECTIES)
    return jsonify({"ok": True, "wachtrij": wachtrij})


@app.get("/api/status")
def api_status():
    vanaf = int(request.args.get("vanaf", 0))
    with LOCK:
        return jsonify({
            "actief": STAAT["actief"],
            "run": STAAT["run"],
            "onderwerp": STAAT["onderwerp"],
            "totaal": STAAT["totaal"],
            "aantal": len(STAAT["beurten"]),
            "nieuwe": STAAT["beurten"][vanaf:],
            "bezig_met": STAAT["bezig_met"],
            "fout": STAAT["fout"],
            "stop_gevraagd": STAAT["stop_gevraagd"],
            "modus": STAAT["modus"],
            "werkmap": STAAT["werkmap"],
            "tak": STAAT["tak"],
            "wachtrij": len(INJECTIES),
        })


@app.get("/api/onderwerpen")
def api_onderwerpen():
    lijst = []
    for pad in sorted(ONDERWERPEN.glob("*.json")):
        try:
            lijst.append({"bestand": pad.name, **json.loads(pad.read_text(encoding="utf-8"))})
        except (json.JSONDecodeError, OSError):
            continue
    return jsonify(lijst)


@app.post("/api/onderwerp")
def api_onderwerp_opslaan():
    gegevens = request.get_json(force=True)
    naam = "".join(t for t in gegevens.get("bestand", "") if t.isalnum() or t in "-_")
    if not naam:
        return jsonify({"fout": "geen geldige bestandsnaam"}), 400
    inhoud = {k: gegevens[k] for k in ("vraag", "context", "claude", "codex")}
    for optioneel in ("briefing", "projectmap"):
        if gegevens.get(optioneel):
            inhoud[optioneel] = gegevens[optioneel]
    ONDERWERPEN.mkdir(exist_ok=True)
    (ONDERWERPEN / f"{naam}.json").write_text(
        json.dumps(inhoud, ensure_ascii=False, indent=2), encoding="utf-8")
    return jsonify({"ok": True, "bestand": f"{naam}.json"})


@app.get("/api/modellen")
def api_modellen():
    """De modellen die op deze machine en deze accounts echt werken.

    Welke namen geldig zijn verschilt per account en per CLI-versie, dus dit staat
    in modellen.json en wordt bijgewerkt door controleer_modellen.py.
    """
    # modellen.json is per machine (niet in git); tot die er is geldt de veilige standaard.
    bron = MODELLEN if MODELLEN.exists() else BASIS / "modellen.standaard.json"
    return jsonify(json.loads(bron.read_text(encoding="utf-8")))


@app.get("/api/mappen")
def api_mappen():
    """Bladeren door mappen op deze machine, voor het kiezen van een projectmap."""
    ruw = request.args.get("pad", "").strip()
    pad = Path(ruw).resolve() if ruw else STARTMAP.resolve()
    if not pad.is_dir():
        pad = STARTMAP.resolve()
    try:
        mappen = sorted(
            (p for p in pad.iterdir() if p.is_dir() and not p.name.startswith(".")),
            key=lambda p: p.name.lower())
    except OSError as e:
        return jsonify({"fout": str(e)}), 400
    return jsonify({
        "pad": str(pad),
        "omhoog": str(pad.parent) if pad.parent != pad else None,
        "is_repo": (pad / ".git").exists(),
        "mappen": [{"naam": p.name, "pad": str(p), "is_repo": (p / ".git").exists()}
                   for p in mappen],
    })


def _maak_briefing(pad, woorden, model):
    try:
        resultaat = verkenner.maak_briefing(
            pad, woorden=woorden, model=model,
            registreer=lambda p: BRIEFING.__setitem__("proc", p))
        BRIEFING["resultaat"] = resultaat
    except Exception as e:
        BRIEFING["fout"] = str(e)[:800]
    finally:
        BRIEFING["bezig"] = False
        BRIEFING["proc"] = None


@app.post("/api/briefing")
def api_briefing_start():
    if BRIEFING["bezig"]:
        return jsonify({"fout": "er loopt al een briefing"}), 409
    gegevens = request.get_json(force=True)
    pad = gegevens.get("pad", "").strip()
    if not Path(pad).is_dir():
        return jsonify({"fout": "geen geldige map"}), 400
    BRIEFING.update({"bezig": True, "fout": None, "resultaat": None, "proc": None})
    threading.Thread(
        target=_maak_briefing,
        args=(pad, max(150, min(1500, int(gegevens.get("woorden", 500)))),
              gegevens.get("model", "sonnet")),
        daemon=True).start()
    return jsonify({"ok": True})


@app.get("/api/briefing")
def api_briefing_status():
    return jsonify({k: BRIEFING[k] for k in ("bezig", "fout", "resultaat")})


@app.post("/api/controleer")
def api_controleer():
    """Toetst een (handmatig aangepaste) briefing op gegevens die niet weg mogen."""
    tekst = request.get_json(force=True).get("tekst", "")
    return jsonify({"waarschuwingen": verkenner.controleer_briefing(tekst)})


@app.post("/api/briefing/stop")
def api_briefing_stop():
    debat.stop_proces(BRIEFING.get("proc"))
    return jsonify({"ok": True})


@app.get("/api/runs")
def api_runs():
    lijst = []
    mappen = sorted((p for p in RUNS.iterdir() if p.is_dir()), reverse=True) if RUNS.is_dir() else []
    for pad in mappen:
        board = pad / "board.jsonl"
        if not board.exists():
            continue
        try:
            onderwerp = json.loads((pad / "onderwerp.json").read_text(encoding="utf-8"))
            vraag = onderwerp["vraag"]
        except (OSError, json.JSONDecodeError, KeyError):
            vraag = "(onbekend onderwerp)"
        aantal = sum(1 for _ in board.open(encoding="utf-8"))
        lijst.append({"naam": pad.name, "vraag": vraag, "beurten": aantal})
    return jsonify(lijst)


@app.get("/api/run/<naam>")
def api_run(naam):
    pad = (RUNS / naam).resolve()
    if pad.parent != RUNS.resolve() or not pad.is_dir():
        return jsonify({"fout": "niet gevonden"}), 404
    beurten = [json.loads(r) for r in (pad / "board.jsonl").open(encoding="utf-8") if r.strip()]
    onderwerp = json.loads((pad / "onderwerp.json").read_text(encoding="utf-8"))
    return jsonify({"naam": naam, "onderwerp": onderwerp, "beurten": beurten})


@app.get("/")
def index():
    return Response((BASIS / "pagina.html").read_text(encoding="utf-8"), mimetype="text/html")


if __name__ == "__main__":
    if "--geen-browser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{POORT}")).start()
    app.run(host="127.0.0.1", port=POORT, threaded=True)
