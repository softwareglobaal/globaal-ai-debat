"""Rondes tussen Claude en Codex als run in het dashboard.

Claude roept Codex aan met ~/.claude/tools/codex.sh (codex exec). Dat script schrijft elke ronde
met dit bestand weg als run, zoals een debat of opdracht: runs/<tijdstip>-codex/ met
onderwerp.json, board.jsonl en transcript.md. In de interface staat ze links bij de eerdere runs.

    python ronde.py nieuw --titel "..." [--map PAD] [--rapport PAD] [--model M] [--niveau N]
                          [--sandbox S] [--tijd ISO] [--naambestand PAD] < opdracht.md   # drukt de naam af
    python ronde.py beurt <ronde> --kant codex --soort controle [--model M] [--duur S] < antwoord.md
    python ronde.py beurt <ronde> --kant claude --soort verwerking < verwerkt.md

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
}
NAAM = re.compile(r"^\d{8}-\d{6}-codex(-\d+)?$")
BESTANDEN = ("board.jsonl", "onderwerp.json", "transcript.md")
UITKOMST = ("controle", "fout")   # een ronde krijgt er precies een
SLOT_WACHT_S = 10                 # zo lang wacht een beurt op een andere beurt van dezelfde ronde
_NA_LEZEN = None                  # alleen voor tests: aangeroepen binnen het slot, tussen lezen en schrijven


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


@contextmanager
def _slot(pad: Path):
    """Eén beurt tegelijk per ronde, met een slot van het besturingssysteem op .slot. Het komt vrij zodra
    de houder stopt, ook na een crash, en niemand kan het afpakken zolang de houder leeft. Het bestand blijft
    staan; weggooien zou zelf een wedloop geven."""
    slot = pad / ".slot"
    if slot.is_symlink() or (slot.exists() and not slot.is_file()):
        raise ValueError(f"onverwacht slot, geen gewoon bestand: {slot}")
    vlaggen = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(slot, vlaggen, 0o600)
    try:
        einde = time.monotonic() + SLOT_WACHT_S
        while not _probeer_slot(fd):
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


def voeg_toe(pad: Path, kant: str, soort: str, tekst: str, model: str = "",
             duur=None, tijd=None) -> dict:
    if (kant, soort) not in SPREKERS:
        raise ValueError(f"onbekende beurt: kant {kant!r}, soort {soort!r}")
    tekst = (tekst or "").strip()
    if not tekst:
        raise ValueError("tekst is leeg")
    duur_s = _duur(duur)
    _geen_symlinks(pad)
    with _slot(pad):
        _geen_symlinks(pad)
        beurten = _beurten(pad)
        uitkomst = [b["soort"] for b in beurten if b.get("soort") in UITKOMST]
        if soort in UITKOMST and uitkomst:
            raise ValueError(f"ronde {pad.name} heeft al een uitkomst ({uitkomst[0]})")
        if soort == "verwerking" and not uitkomst:
            raise ValueError(f"ronde {pad.name} heeft nog geen antwoord of fout van Codex")
        if _NA_LEZEN:
            _NA_LEZEN()
        beurt = {
            "nr": len(beurten) + 1,
            "spreker": SPREKERS[(kant, soort)],
            "kant": kant,
            "soort": soort,
            "model": model or "",
            "tijd": _tijd(tijd),
            "duur_s": duur_s,
            "tekst": tekst,
        }
        with (pad / "board.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(beurt, ensure_ascii=False, allow_nan=False) + "\n")
        onderwerp = json.loads((pad / "onderwerp.json").read_text(encoding="utf-8"))
        debat.schrijf_transcript(pad, onderwerp, beurten + [beurt])
    return beurt


def nieuw(titel: str, opdracht: str, tijd=None, naambestand=None, **gegevens) -> str:
    """Maakt de ronde met de opdracht als eerste beurt en geeft de naam terug. Met naambestand staat
    de naam ook meteen op schijf, zodat codex.sh hem vindt als het onderbroken wordt voor het hem las."""
    titel = " ".join((titel or "").split())
    if not titel:
        raise ValueError("titel is leeg")
    if not (opdracht or "").strip():
        raise ValueError("opdracht is leeg")
    moment = datetime.fromisoformat(tijd) if tijd else datetime.now()
    basis = moment.strftime("%Y%m%d-%H%M%S") + "-codex"
    runs = _runs()
    runs.mkdir(parents=True, exist_ok=True)
    naam, i = basis, 1
    while True:
        try:
            (runs / naam).mkdir()
            break
        except FileExistsError:
            i += 1
            naam = f"{basis}-{i}"
    pad = runs / naam
    onderwerp = {"vraag": titel, "modus": "ronde", **{k: v for k, v in gegevens.items() if v}}
    (pad / "onderwerp.json").write_text(json.dumps(onderwerp, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    (pad / "board.jsonl").write_text("", encoding="utf-8")
    if naambestand:
        Path(naambestand).write_text(naam + "\n", encoding="utf-8")
    voeg_toe(pad, "claude", "opdracht", opdracht, model="Claude Code", tijd=moment.isoformat())
    return naam


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Ronde tussen Claude en Codex in het dashboard")
    p.add_argument("--runs", help="andere runs-map (tests en zelftest)")
    sub = p.add_subparsers(dest="actie", required=True)

    n = sub.add_parser("nieuw")
    n.add_argument("--titel", required=True)
    for veld in ("map", "rapport", "model", "niveau", "sandbox", "tijd", "naambestand"):
        n.add_argument(f"--{veld}", default="")

    b = sub.add_parser("beurt")
    b.add_argument("ronde")
    b.add_argument("--kant", required=True, choices=["claude", "codex"])
    b.add_argument("--soort", required=True, choices=["controle", "fout", "verwerking"])
    b.add_argument("--model", default="")
    b.add_argument("--duur", default="")
    b.add_argument("--tijd", default="")

    a = p.parse_args(argv)
    if a.runs:
        debat.RUNS = Path(a.runs)
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
