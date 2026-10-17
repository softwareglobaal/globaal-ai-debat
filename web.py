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
    "vonnis": None,
    "stop_reden": None,
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
    # Kwam Nu stoppen net voor dit proces geregistreerd was, dan zag api_stop het niet:
    # hier alsnog afschieten. Beide kanten lezen onder LOCK, dus een van de twee ziet het.
    with LOCK:
        HUIDIG["proc"] = proc
        te_laat = proc is not None and STAAT["stop_gevraagd"]
    if te_laat:
        debat.stop_proces(proc)


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
        modus="debat", werkmap=None, tak=None, vonnis=None, stop_reden=None)

    systeem = debat.HUISREGELS.format(max_woorden=config["max_woorden"])
    kanten = {
        "claude": {
            "rol": onderwerp["claude"], "roep": debat.roep_claude,
            "model": config["claude_model"], "niveau": config.get("claude_niveau", ""),
        },
        "codex": {
            "rol": onderwerp["codex"], "roep": debat.roep_codex,
            "model": config["codex_model"], "niveau": config.get("codex_niveau", ""),
        },
    }
    beurt_aan = config["start"]

    def moderator_inbrengen(nr):
        """Moderatorberichten die jij intussen hebt ingestuurd. Geeft terug of er iets was."""
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
        return bool(wachtend)

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
            # Een fout halverwege beeindigt het debat, maar niet zonder vonnis over wat er al ligt.
            try:
                extra = {"niveau": kant["niveau"]} if kant.get("niveau") else {}
                tekst = kant["roep"](systeem, prompt, kant["model"], config["timeout"],
                                     registreer_proces, **extra)
            except Exception as e:
                if not gestopt():
                    zet(fout=str(e)[:800])
                break
            if gestopt():
                break
            tekst, standpunt = debat.splits_standpunt(tekst)
            if not tekst and not standpunt:
                zet(fout=f"{label} gaf een leeg antwoord")
                break
            tekst = tekst or debat.ALLEEN_STANDPUNT.format(standpunt)

            model_label = kant["model"] or "standaard"
            if kant.get("niveau"):
                model_label = f"{model_label} · {kant['niveau']}"
            voeg_beurt_toe({
                "nr": nr,
                "spreker": label,
                "kant": beurt_aan,
                "model": model_label,
                "tijd": datetime.now().isoformat(timespec="seconds"),
                "duur_s": round(time.time() - begin, 1),
                "tekst": tekst,
                "standpunt": standpunt,
            }, run_dir)

            nieuw_punt = moderator_inbrengen(nr)

            # Verder praten na wederzijdse instemming levert niets meer op, tenzij jij net
            # een nieuw punt hebt ingebracht: dat krijgt eerst nog een antwoord.
            with LOCK:
                eens = debat.beide_eens(STAAT["beurten"])
            if eens and not nieuw_punt:
                zet(stop_reden="beide kanten melden EENS")
                break

            beurt_aan = "codex" if beurt_aan == "claude" else "claude"

        # Elk debat dat niet is afgebroken eindigt met een vonnis. Vanaf hier neemt
        # api_injectie niets meer aan; wat nog wachtte, gaat mee naar de rechter.
        with LOCK:
            afgebroken = STAAT["stop_gevraagd"]
            rechter = not afgebroken and sum(b["kant"] != "mens" for b in STAAT["beurten"]) >= 2
            if rechter:
                STAAT["bezig_met"] = "RECHTER"
            laatste_nr = STAAT["beurten"][-1]["nr"] if STAAT["beurten"] else 0
        if rechter:
            moderator_inbrengen(laatste_nr)
            with LOCK:
                geschiedenis = list(STAAT["beurten"])
            try:
                vonnis = debat.velle_vonnis(onderwerp, geschiedenis, config["claude_model"],
                                            config["timeout"], registreer_proces)
            except Exception as e:
                vonnis = {"fout": str(e)[:800], "rechter": config["claude_model"]}
            with LOCK:
                afgebroken = STAAT["stop_gevraagd"]
            if not afgebroken:
                debat.schrijf_vonnis(run_dir, onderwerp, geschiedenis, vonnis)
                zet(vonnis=vonnis)
    except Exception as e:
        # Een afgeschoten proces geeft een exitcode-fout; dat is geen storing.
        with LOCK:
            door_gebruiker = STAAT["stop_gevraagd"]
        if not door_gebruiker:
            zet(fout=str(e)[:800])
    finally:
        registreer_proces(None)
        zet(actief=False, bezig_met=None)


def gestopt():
    with LOCK:
        return STAAT["stop_gevraagd"]


def schrijf_resultaat(run_dir, resultaat):
    (run_dir / "resultaat.json").write_text(
        json.dumps(resultaat, ensure_ascii=False, indent=2), encoding="utf-8")


def draai_opdracht(onderwerp, config):
    """Uitvoerder schrijft, de app test, uitvoerder herstelt tot de tests groen zijn. In een
    worktree. De ChatGPT-reviewer is eruit (testset 16-10-2026, zie opdracht.py)."""
    run_dir = RUNS / datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "onderwerp.json").write_text(
        json.dumps(onderwerp, ensure_ascii=False, indent=2), encoding="utf-8")

    commando = config["testcommando"]
    # Zonder tests is er niets om in een volgende ronde op te herstellen: altijd een ronde.
    rondes = config["rondes"] if commando else 1
    stappen = rondes * (1 + bool(commando)) + bool(commando)
    zet(actief=True, run=run_dir.name, onderwerp=onderwerp, beurten=[],
        totaal=stappen, fout=None, stop_gevraagd=False, bezig_met=None,
        modus="opdracht", werkmap=None, tak=None, vonnis=None, stop_reden=None)

    claude_niveau = config.get("claude_niveau", "")
    uitvoerder_label = f"{config['claude_model']} · {claude_niveau}" if claude_niveau else config["claude_model"]

    # De feiten van deze run als velden; het oordeel vul jij later in de tabel in. Variant
    # blijft 'solo', zodat oude duo-runs in de tabel ernaast te vergelijken blijven.
    resultaat = {
        "label": config["label"], "variant": "solo",
        "repo": Path(onderwerp["repo"]).name, "opdracht": onderwerp["vraag"],
        "uitvoerder": uitvoerder_label, "reviewer": None,
        "testcommando": commando or None, "tak": None,
        "rondes_gepland": rondes, "rondes_gedraaid": 0,
        "tests_start": None, "tests_per_ronde": [], "tests_eind": None,
        "duur_s": None, "stop_reden": None, "fout": None,
        "oordeel": {"terecht": None, "totaal": None, "bruikbaar": None, "notitie": ""},
    }
    start = time.time()
    nr = 0

    def test_stap(naam, bestand):
        nonlocal nr
        zet(bezig_met=f"TESTS ({naam})")
        test = opdracht.draai_tests(werkmap, commando, config["test_timeout"], registreer_proces)
        # Nu stoppen doodt de tests; die exitcode is geen uitslag en mag niet als rood tellen.
        if gestopt():
            test["groen"] = None
        (run_dir / f"tests-{bestand}.txt").write_text(test["uitvoer"], encoding="utf-8")
        nr += 1
        voeg_beurt_toe({
            "nr": nr, "spreker": f"TESTS ({naam})", "kant": "test", "soort": "tests",
            "model": "app", "tijd": datetime.now().isoformat(timespec="seconds"),
            "duur_s": test["duur_s"],
            "tekst": ("AFGEBROKEN (door jou gestopt)" if test["groen"] is None
                      else opdracht.testuitslag(test)),
            "test": {k: test[k] for k in ("commando", "exitcode", "groen", "timeout", "opgeruimd",
                                          "niet_opgeruimd")},
            "uitvoer": opdracht.staart(test["uitvoer"], opdracht.TESTSTAART_SCHERM),
            "uitvoer_bestand": f"tests-{bestand}.txt",
        }, run_dir)
        return test

    try:
        werkmap, tak = opdracht.maak_worktree(Path(onderwerp["repo"]))
        zet(werkmap=str(werkmap), tak=tak)
        resultaat["tak"] = tak

        test = None
        if commando:
            test = test_stap("startpunt", "start")
            if not gestopt():
                resultaat["tests_start"] = test["groen"]

        vorige_diff = ""
        for ronde in range(1, rondes + 1):
            if gestopt():
                break

            # De uitvoerder schrijft of herstelt.
            zet(bezig_met=f"UITVOERDER (ronde {ronde})")
            begin = time.time()
            extra = {"niveau": claude_niveau} if claude_niveau else {}
            verslag = opdracht.roep_uitvoerder(
                opdracht.UITVOERDER.format(woorden=config["max_woorden"]),
                opdracht.uitvoer_prompt(onderwerp["opdracht"], ronde, test, commando),
                config["claude_model"], config["timeout"], werkmap,
                config["bash"], registreer_proces, **extra)
            if gestopt():
                break
            verschil = opdracht.diff_van(werkmap)
            nr += 1
            voeg_beurt_toe({
                "nr": nr, "spreker": f"UITVOERDER (Claude, ronde {ronde})",
                "kant": "claude", "soort": "uitvoering",
                "model": uitvoerder_label,
                "tijd": datetime.now().isoformat(timespec="seconds"),
                "duur_s": round(time.time() - begin, 1),
                "tekst": verslag,
                "diff": verschil["diff"],
                "bestanden": {k: verschil[k] for k in ("toegevoegd", "gewijzigd", "verwijderd")},
            }, run_dir)
            resultaat["rondes_gedraaid"] = ronde

            if not verschil["diff"].strip():
                zet(fout="de uitvoerder heeft niets gewijzigd, run gestopt")
                resultaat["stop_reden"] = "uitvoerder wijzigde niets"
                break
            # De diff telt alles sinds de start; gelijk aan vorige ronde = deze ronde niets
            # gedaan. Dezelfde tests nog eens draaien levert dan niets nieuws op.
            if verschil["diff"] == vorige_diff:
                resultaat["stop_reden"] = "uitvoerder wijzigde niets meer"
                break
            vorige_diff = verschil["diff"]

            if commando:
                test = test_stap(f"na ronde {ronde}", f"ronde-{ronde}")
                if gestopt():
                    break
                resultaat["tests_per_ronde"].append(test["groen"])
                resultaat["tests_eind"] = test["groen"]

            # Alleen rode tests geven een volgende ronde iets om op te herstellen.
            if not commando:
                resultaat["stop_reden"] = "geen tests: een ronde"
                break
            if test["groen"]:
                resultaat["stop_reden"] = "tests groen"
                break
        else:
            resultaat["stop_reden"] = resultaat["stop_reden"] or "alle rondes gedraaid"
    except Exception as e:
        if not gestopt():
            zet(fout=str(e)[:800])
            resultaat["fout"] = str(e)[:800]
    finally:
        registreer_proces(None)
        if gestopt():
            resultaat["stop_reden"] = "door jou gestopt"
        resultaat["duur_s"] = round(time.time() - start, 1)
        zet(stop_reden=resultaat["stop_reden"])
        schrijf_resultaat(run_dir, resultaat)
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
        "claude_niveau": str(gegevens.get("claude_niveau") or "").strip(),
        "bash": bool(gegevens.get("bash", False)),
        "testcommando": str(gegevens.get("testcommando") or "").strip()[:500],
        "label": "".join(t for t in str(gegevens.get("label") or "") if t.isalnum() or t in "-_ ")[:40].strip(),
        "timeout": 1800,
        "test_timeout": 600,
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
        "claude_niveau": str(gegevens.get("claude_niveau") or "").strip(),
        "codex_model": gegevens.get("codex_model", ""),
        "codex_niveau": str(gegevens.get("codex_niveau") or "").strip(),
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
        # Alleen zolang er nog een debatbeurt komt; daarna zou het bericht stil verdwijnen.
        if not STAAT["actief"] or STAAT["modus"] != "debat" or STAAT["bezig_met"] == "RECHTER":
            return jsonify({"fout": "het debat neemt geen inbreng meer aan"}), 409
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
            # Voor de teller: moderatorberichten zijn geen beurten van het debat.
            "debatbeurten": sum(1 for b in STAAT["beurten"] if b.get("kant") != "mens"),
            "vonnis": STAAT["vonnis"],
            "stop_reden": STAAT["stop_reden"],
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
    standaard = json.loads((BASIS / "modellen.standaard.json").read_text(encoding="utf-8"))
    if MODELLEN.exists():
        data = json.loads(MODELLEN.read_text(encoding="utf-8"))
        for sleutel in ("gemini", "niveaus"):
            if sleutel not in data:
                data[sleutel] = standaard.get(sleutel, [] if sleutel == "gemini" else {})
        return jsonify(data)
    return jsonify(standaard)


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
    # Verborgen mappen (runs/.nieuw-*) zijn rondes in opbouw of resten van een onderbreking.
    mappen = sorted((p for p in RUNS.iterdir() if p.is_dir() and not p.name.startswith(".")),
                    reverse=True) if RUNS.is_dir() else []
    for pad in mappen:
        board = pad / "board.jsonl"
        if not board.exists():
            continue
        try:
            onderwerp = json.loads((pad / "onderwerp.json").read_text(encoding="utf-8"))
            vraag = onderwerp["vraag"]
            modus = onderwerp.get("modus", "")
        except (OSError, json.JSONDecodeError, KeyError):
            vraag, modus = "(onbekend onderwerp)", ""
        with board.open(encoding="utf-8") as f:
            # Zelfde telling als live: moderatorberichten zijn geen beurten.
            aantal = sum(1 for r in f if r.strip() and not is_moderator(r))
        resultaat = lees_json(pad / "resultaat.json") or {}
        lijst.append({"naam": pad.name, "vraag": vraag, "beurten": aantal, "modus": modus,
                      "label": resultaat.get("label"), "variant": resultaat.get("variant"),
                      "vonnis": (pad / "vonnis.json").exists()})
    return jsonify(lijst)


def is_moderator(regel):
    try:
        return json.loads(regel).get("kant") == "mens"
    except (json.JSONDecodeError, AttributeError):
        return False


def run_map(naam):
    pad = (RUNS / naam).resolve()
    return pad if pad.parent == RUNS.resolve() and pad.is_dir() else None


def lees_json(pad):
    try:
        return json.loads(pad.read_text(encoding="utf-8")) if pad.exists() else None
    except (OSError, json.JSONDecodeError):
        return None


@app.get("/api/run/<naam>")
def api_run(naam):
    pad = run_map(naam)
    if not pad:
        return jsonify({"fout": "niet gevonden"}), 404
    # Een opdracht die strandde voor de eerste beurt (bv. geen worktree) heeft wel een
    # resultaat maar geen board.jsonl; die moet vanuit de resultatentabel te openen zijn.
    beurten = []
    if (pad / "board.jsonl").exists():
        with (pad / "board.jsonl").open(encoding="utf-8") as f:
            beurten = [json.loads(r) for r in f if r.strip()]
    onderwerp = lees_json(pad / "onderwerp.json") or {"vraag": "(onbekend onderwerp)"}
    return jsonify({"naam": naam, "onderwerp": onderwerp, "beurten": beurten,
                    "vonnis": lees_json(pad / "vonnis.json"),
                    "resultaat": lees_json(pad / "resultaat.json")})


@app.get("/api/resultaten")
def api_resultaten():
    """Alle opdrachtruns met een resultaat, voor de vergelijking solo tegen duo."""
    lijst = []
    for pad in sorted(RUNS.glob("*/resultaat.json")) if RUNS.is_dir() else []:
        r = lees_json(pad)
        if r:
            lijst.append({"run": pad.parent.name, **r})
    lijst.sort(key=lambda r: (r.get("label") or "~", r["run"]))
    return jsonify(lijst)


@app.post("/api/resultaat/<naam>")
def api_resultaat_oordeel(naam):
    """Jouw oordeel over een run: hoeveel reviewpunten terecht waren en of het bruikbaar is."""
    pad = run_map(naam)
    resultaat = lees_json(pad / "resultaat.json") if pad else None
    if not resultaat:
        return jsonify({"fout": "niet gevonden"}), 404
    gegevens = request.get_json(force=True)

    def getal(waarde):
        try:
            return max(0, int(waarde)) if str(waarde).strip() != "" else None
        except (TypeError, ValueError):
            return None

    bruikbaar = gegevens.get("bruikbaar")
    resultaat["oordeel"] = {
        "terecht": getal(gegevens.get("terecht")),
        "totaal": getal(gegevens.get("totaal")),
        "bruikbaar": bruikbaar if bruikbaar in (True, False) else None,
        "notitie": str(gegevens.get("notitie") or "")[:500],
    }
    schrijf_resultaat(pad, resultaat)
    return jsonify({"ok": True, "oordeel": resultaat["oordeel"]})


@app.get("/")
def index():
    return Response((BASIS / "pagina.html").read_text(encoding="utf-8"), mimetype="text/html")


if __name__ == "__main__":
    if "--geen-browser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{POORT}")).start()
    app.run(host="127.0.0.1", port=POORT, threaded=True)
