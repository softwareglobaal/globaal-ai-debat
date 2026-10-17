"""Rondes tussen Claude en Codex als run in het dashboard.

Claude roept Codex aan met ~/.claude/tools/codex.sh (codex exec). Dat script schrijft elke ronde
met dit bestand weg als run, zoals een debat of opdracht: runs/<tijdstip>-codex/ met
onderwerp.json, board.jsonl en transcript.md. In de interface staat ze links bij de eerdere runs.

    python ronde.py nieuw --titel "..." [--map PAD] [--rapport PAD] [--model M] [--niveau N]
                          [--sandbox S] [--tijd ISO] [--naambestand PAD] < opdracht.md   # drukt de naam af
    python ronde.py beurt <ronde> --kant codex --soort controle [--model M] [--duur S] < antwoord.md
    python ronde.py beurt <ronde> --kant claude --soort verwerking < verwerkt.md
    python ronde.py resten [--weg] [--minuten 10]     # onvolledige rondes na een harde stop

Een ronde: OPDRACHT (Claude aan Codex), dan precies een uitkomst: CONTROLE (Codex) of FOUT, en daarna
VERWERKING (Claude). Een tweede uitkomst en een verwerking zonder uitkomst worden geweigerd.
Alleen standaardbibliotheek.
"""

import argparse
import errno
import json
import math
import os
import re
import shutil
import stat
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
    import msvcrt

import debat

SPREKERS = {
    ("claude", "opdracht"): "OPDRACHT (Claude aan Codex)",
    ("codex", "controle"): "CONTROLE (Codex)",
    ("codex", "fout"): "FOUT (Codex stopte)",
    ("claude", "verwerking"): "VERWERKING (Claude)",
    ("gemini", "advies"): "ADVIES (Gemini)",
    ("gemini", "fout"): "FOUT (Gemini stopte)",
    ("codex", "overleg"): "OVERLEG (Codex)",
    ("gemini", "overleg"): "OVERLEG (Gemini)",
    ("claude", "overleg"): "OVERLEG (Claude)",
}
NAAM = re.compile(r"^\d{8}-\d{6}-codex(-\d+)?$")
BESTANDEN = ("board.jsonl", "onderwerp.json", "transcript.md")
UITKOMST = ("controle", "fout")   # een ronde krijgt per kant precies een uitkomst
SLOT_WACHT_S = 10                 # zo lang wacht een beurt op een andere beurt van dezelfde ronde
_NA_LEZEN = None                  # alleen voor tests: aangeroepen binnen het slot, tussen lezen en schrijven
STAPPEN_NIEUW = ("gereserveerd", "naam", "zichtbaar")
_NA_MISLUKTE_POGING = None        # alleen voor tests: aangeroepen als het slot bezet bleek
RESTEN_OUDER_DAN_S = 600          # een onvolledige ronde die ouder is, is een rest van een harde stop
_NA_STAP = None                   # alleen voor tests: aangeroepen na elke stap van nieuw()


def _runs() -> Path:
    # Via de module opgezocht, zodat tests en --runs een andere map kunnen geven.
    return debat.RUNS


def _geen_symlinks(pad: Path) -> None:
    """Een ronde en haar bestanden zijn echte bestanden in runs/; een symlink kan naar buiten wijzen."""
    for p in (pad, *(pad / b for b in BESTANDEN)):
        if p.is_symlink():
            raise ValueError(f"symlink geweigerd: {p}")
    if pad.resolve().parent != _runs().resolve():
        raise ValueError(f"ronde ligt buiten {_runs()}: {pad}")


def run_pad(naam: str) -> Path:
    """Alleen een bestaande ronde in runs/, nooit een pad erbuiten."""
    if not NAAM.match(naam or ""):
        raise ValueError(f"geen rondenaam: {naam!r}")
    pad = _runs() / naam
    _geen_symlinks(pad)
    if not (pad / "board.jsonl").is_file():
        raise FileNotFoundError(f"ronde {naam} bestaat niet in {_runs()}")
    return pad


def _probeer_slot(fd: int) -> bool:
    try:
        if fcntl:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        return True
    except OSError as e:  # bezet: BlockingIOError (POSIX) of EACCES/EDEADLK (Windows)
        if isinstance(e, BlockingIOError) or e.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
            return False
        raise


def _laat_slot(fd: int) -> None:
    if fcntl:
        fcntl.flock(fd, fcntl.LOCK_UN)
    else:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


def _controleer_geopend(fd: int, slot: Path) -> None:
    """Wat geopend werd, moet het gewone bestand .slot zelf zijn. Zonder O_NOFOLLOW (Windows) kan een ander
    proces .slot tussen controle en open door een symlink vervangen; dan wijst de open naar een ander bestand."""
    geopend = os.fstat(fd)
    try:
        op_pad = os.lstat(slot)
    except OSError as e:
        raise ValueError(f"slot verdween tijdens het openen: {slot}") from e
    if (not stat.S_ISREG(geopend.st_mode) or stat.S_ISLNK(op_pad.st_mode)
            or (geopend.st_dev, geopend.st_ino) != (op_pad.st_dev, op_pad.st_ino)):
        raise ValueError(f"geopend slot is niet het gewone bestand {slot}")


@contextmanager
def _slot(pad: Path):
    """Eén beurt tegelijk per ronde, met een slot van het besturingssysteem op .slot. Het komt vrij zodra
    de houder stopt, ook na een crash, en niemand kan het afpakken zolang de houder leeft. Het bestand blijft
    staan; weggooien zou zelf een wedloop geven."""
    slot = pad / ".slot"
    if slot.is_symlink() or (slot.exists() and not slot.is_file()):
        raise ValueError(f"onverwacht slot, geen gewoon bestand: {slot}")
    vlaggen = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        # O_EXCL maakt alleen een nieuw bestand en volgt nooit een symlink, ook niet op Windows.
        fd = os.open(slot, vlaggen | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        try:
            fd = os.open(slot, vlaggen)  # zonder O_CREAT: een symlink naar niets maakt buiten runs/ niets aan
        except OSError as e:
            raise ValueError(f"slot niet te openen als gewoon bestand: {slot} ({e})") from e
    try:
        _controleer_geopend(fd, slot)
        einde = time.monotonic() + SLOT_WACHT_S
        while not _probeer_slot(fd):
            if _NA_MISLUKTE_POGING:
                _NA_MISLUKTE_POGING()
            if time.monotonic() > einde:
                raise TimeoutError(f"ronde {pad.name} is bezet")
            time.sleep(0.02)
        try:
            yield
        finally:
            _laat_slot(fd)
    finally:
        os.close(fd)


def _duur(duur):
    if duur in (None, ""):
        return None
    waarde = float(duur)
    if not math.isfinite(waarde) or waarde < 0:
        raise ValueError(f"duur moet een eindig getal van 0 of meer zijn, niet {duur!r}")
    return round(waarde, 1)


def _beurten(pad: Path) -> list:
    with (pad / "board.jsonl").open(encoding="utf-8") as f:
        return [json.loads(r) for r in f if r.strip()]


def _tijd(tijd) -> str:
    moment = datetime.fromisoformat(tijd) if tijd else datetime.now()
    return moment.isoformat(timespec="seconds")


def _maak_beurt(nr: int, kant: str, soort: str, tekst: str, model: str = "", duur=None, tijd=None) -> dict:
    if (kant, soort) not in SPREKERS:
        raise ValueError(f"onbekende beurt: kant {kant!r}, soort {soort!r}")
    tekst = (tekst or "").strip()
    if not tekst:
        raise ValueError("tekst is leeg")
    return {
        "nr": nr,
        "spreker": SPREKERS[(kant, soort)],
        "kant": kant,
        "soort": soort,
        "model": model or "",
        "tijd": _tijd(tijd),
        "duur_s": _duur(duur),
        "tekst": tekst,
    }


def voeg_toe(pad: Path, kant: str, soort: str, tekst: str, model: str = "",
             duur=None, tijd=None) -> dict:
    _maak_beurt(0, kant, soort, tekst, model, duur, tijd)  # invoer controleren voor het slot
    _geen_symlinks(pad)
    with _slot(pad):
        _geen_symlinks(pad)
        beurten = _beurten(pad)
        if not beurten or beurten[0].get("soort") != "opdracht":
            raise ValueError(f"ronde {pad.name} begint niet met een opdracht")
        uitkomst = [b["soort"] for b in beurten if b.get("soort") in ("controle", "fout", "advies", "overleg")]
        eigen_uitkomst = [b["soort"] for b in beurten if b.get("kant") == kant and b.get("soort") in ("controle", "fout", "advies")]
        if soort in ("controle", "fout", "advies") and eigen_uitkomst:
            raise ValueError(f"ronde {pad.name} heeft al een uitkomst voor {kant} ({eigen_uitkomst[0]})")
        if soort == "verwerking" and not uitkomst:
            raise ValueError(f"ronde {pad.name} heeft nog geen antwoord of fout van Codex")
        if _NA_LEZEN:
            _NA_LEZEN()
        beurt = _maak_beurt(len(beurten) + 1, kant, soort, tekst, model, duur, tijd)
        with (pad / "board.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(beurt, ensure_ascii=False, allow_nan=False) + "\n")
        onderwerp = json.loads((pad / "onderwerp.json").read_text(encoding="utf-8"))
        debat.schrijf_transcript(pad, onderwerp, beurten + [beurt])
    return beurt


def _stap(naam: str) -> None:
    if _NA_STAP:
        _NA_STAP(naam)


def nieuw(titel: str, opdracht: str, tijd=None, naambestand=None, **gegevens) -> str:
    """Maakt de ronde met de opdracht als eerste beurt en geeft de naam terug.

    1. De naam wordt gereserveerd met mkdir: atomisch, en het vervangt nooit iets, ook geen lege map van een
       ander proces. Pas dan komt de naam in het naambestand, dat dus alleen een eigen ronde kan noemen.
    2. onderwerp.json en transcript.md komen in die map, board.jsonl als laatste via os.replace.
    Zonder board.jsonl is een ronde onzichtbaar (dashboard, run_pad). Een onderbreking laat dus nooit een halve
    ronde zien; een harde stop kan een rest zonder board.jsonl achterlaten, die resten() toont."""
    titel = " ".join((titel or "").split())
    if not titel:
        raise ValueError("titel is leeg")
    if not (opdracht or "").strip():
        raise ValueError("opdracht is leeg")
    moment = datetime.fromisoformat(tijd) if tijd else datetime.now()
    eerste = _maak_beurt(1, "claude", "opdracht", opdracht, model="Claude Code", tijd=moment.isoformat())
    onderwerp = {"vraag": titel, "modus": "ronde", **{k: v for k, v in gegevens.items() if v}}
    runs = _runs()
    runs.mkdir(parents=True, exist_ok=True)
    basis = moment.strftime("%Y%m%d-%H%M%S") + "-codex"
    naam, i = basis, 1
    while True:
        try:
            os.mkdir(runs / naam)
            break
        except FileExistsError:
            i += 1
            naam = f"{basis}-{i}"
    pad = runs / naam
    try:
        _stap("gereserveerd")
        if naambestand:
            Path(naambestand).write_text(naam + "\n", encoding="utf-8")
        _stap("naam")
        (pad / "onderwerp.json").write_text(json.dumps(onderwerp, ensure_ascii=False, indent=2), encoding="utf-8")
        debat.schrijf_transcript(pad, onderwerp, [eerste])
        klaar = pad / ".board.jsonl.nieuw"
        klaar.write_text(json.dumps(eerste, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(klaar, pad / "board.jsonl")
    except BaseException:
        if not (pad / "board.jsonl").exists():
            shutil.rmtree(pad, ignore_errors=True)
        raise
    _stap("zichtbaar")
    return naam


def resten(ouder_dan_s: float = RESTEN_OUDER_DAN_S) -> list:
    """Onvolledige rondes: mappen met een rondenaam maar zonder board.jsonl (een harde stop tijdens nieuw()),
    en verborgen runs/.nieuw-* van codex.sh v1.4. Alleen wat ouder is dan ouder_dan_s; jonger kan nog in opbouw zijn."""
    runs = _runs()
    if not runs.is_dir():
        return []
    gevonden = []
    for d in sorted(runs.iterdir()):
        if d.is_symlink() or not d.is_dir():
            continue
        onvolledig = NAAM.match(d.name) and not (d / "board.jsonl").exists()
        if (onvolledig or d.name.startswith(".nieuw-")) and time.time() - d.stat().st_mtime > ouder_dan_s:
            gevonden.append(d)
    return gevonden


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Ronde tussen Claude, Codex en Gemini in het dashboard")
    p.add_argument("--runs", help="andere runs-map (tests en zelftest)")
    sub = p.add_subparsers(dest="actie", required=True)

    n = sub.add_parser("nieuw")
    n.add_argument("--titel", required=True)
    for veld in ("map", "rapport", "model", "niveau", "sandbox", "tijd", "naambestand"):
        n.add_argument(f"--{veld}", default="")

    r = sub.add_parser("resten", help="onvolledige rondes tonen, met --weg ook weghalen")
    r.add_argument("--weg", action="store_true")
    r.add_argument("--minuten", type=float, default=RESTEN_OUDER_DAN_S / 60)

    b = sub.add_parser("beurt")
    b.add_argument("ronde")
    b.add_argument("--kant", required=True, choices=["claude", "codex", "gemini"])
    b.add_argument("--soort", required=True, choices=["controle", "fout", "verwerking", "advies", "overleg"])
    b.add_argument("--model", default="")
    b.add_argument("--duur", default="")
    b.add_argument("--tijd", default="")

    a = p.parse_args(argv)
    if a.runs:
        debat.RUNS = Path(a.runs)
    if a.actie == "resten":
        for d in resten(a.minuten * 60):
            if a.weg:
                shutil.rmtree(d)
            print(("weg: " if a.weg else "") + str(d))
        return 0
    tekst = sys.stdin.read()
    try:
        if a.actie == "nieuw":
            print(nieuw(a.titel, tekst, tijd=a.tijd or None, project=a.map, rapport=a.rapport,
                        codex_model=a.model, niveau=a.niveau, sandbox=a.sandbox,
                        naambestand=a.naambestand or None))
        else:
            voeg_toe(run_pad(a.ronde), a.kant, a.soort, tekst, model=a.model,
                     duur=a.duur, tijd=a.tijd or None)
            print(a.ronde)
    except (ValueError, OSError) as e:  # TimeoutError is een OSError
        print(f"ronde.py: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
