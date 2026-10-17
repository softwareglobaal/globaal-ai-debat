"""Lokale wachtrij voor read-only overleg vanuit de Terminal van Antigravity.

De luisteraar is het enige proces dat de Antigravity-omgeving erft. Opdrachten,
statussen en logs bevatten uitsluitend taakgegevens en gezuiverde uitvoer.
"""

import argparse
import json
import os
import re
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

if os.name == "posix":
    import fcntl


VERSIE = 1
MAX_OPDRACHT = 200_000
MAX_JSON = 1_000_000  # JSON-escaping kan een geldige opdracht van 200 kB vergroten.
HARTSLAG_GELDIG = 60
HARTSLAG_INTERVAL = 5
STANDAARD_TIJD_LIMIET = 3 * 60 * 60
MAPPEN = ("wachtrij", "bezig", "klaar", "fout")
VELDEN = {"id", "werkmap", "rapport", "titel", "opdracht", "opties"}
OPTIES = {"b", "m", "e", "g", "G", "c", "E", "T", "met_claude"}
NIVEAUS = {
    "e": {"low", "medium", "high", "xhigh", "ultra"},
    "G": {"low", "medium", "high"},
    "E": {"low", "medium", "high", "xhigh", "max"},
}
MODEL = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")
ID = re.compile(r"[0-9]{8}T[0-9]{12}-[0-9a-f]{12}\Z")
ONVEILIGE_TEKENS = re.compile(r"[\x00-\x1f\x7f;&|$`<>\\]")


class BrugFout(Exception):
    """Fout die zonder gevoelige details aan Claude getoond mag worden."""


def brugmap() -> Path:
    return Path(os.environ.get("OVERLEG_BRUG_MAP") or Path.home() / ".overleg-brug").expanduser()


def geheimen_weg(tekst: str) -> str:
    for naam in ("ANTIGRAVITY_CSRF_TOKEN", "ANTIGRAVITY_LS_ADDRESS"):
        waarde = os.environ.get(naam, "")
        if waarde:
            tekst = tekst.replace(waarde, "[afgeschermd]")
            tekst = tekst.replace(json.dumps(waarde, ensure_ascii=True)[1:-1], "[afgeschermd]")
    return tekst


def _veilige_map(pad: Path) -> None:
    if pad.is_symlink():
        raise BrugFout("Wachtrijmap mag geen symlink zijn")
    pad.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = pad.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise BrugFout("Wachtrijpad is geen map")
    if os.name == "posix" and info.st_uid != os.getuid():
        raise BrugFout("Wachtrijmap is niet van de huidige gebruiker")
    if os.name == "posix":
        pad.chmod(0o700)


def maak_mappen(basis: Path) -> None:
    _veilige_map(basis)
    for naam in MAPPEN:
        _veilige_map(basis / naam)


def schrijf_atomisch(pad: Path, inhoud: bytes) -> None:
    tijdelijk = pad.with_name(f".{pad.name}.{uuid.uuid4().hex}.tmp")
    fd = os.open(tijdelijk, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as uitvoer:
            uitvoer.write(inhoud)
            uitvoer.flush()
            os.fsync(uitvoer.fileno())
        os.replace(tijdelijk, pad)
    finally:
        tijdelijk.unlink(missing_ok=True)


def schrijf_json(pad: Path, gegevens: dict) -> None:
    def zuiver(waarde):
        if isinstance(waarde, str):
            return geheimen_weg(waarde)
        if isinstance(waarde, dict):
            return {geheimen_weg(k) if isinstance(k, str) else k: zuiver(v)
                    for k, v in waarde.items()}
        if isinstance(waarde, list):
            return [zuiver(v) for v in waarde]
        return waarde

    tekst = json.dumps(zuiver(gegevens), ensure_ascii=False, sort_keys=True)
    schrijf_atomisch(pad, (tekst + "\n").encode("utf-8"))


def _zonder_dubbele_velden(paren):
    gegevens = {}
    for sleutel, waarde in paren:
        if sleutel in gegevens:
            raise BrugFout("Dubbel veld in opdracht")
        gegevens[sleutel] = waarde
    return gegevens


def _lees_json_veilig(pad: Path) -> dict:
    vlaggen = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(pad, vlaggen)
    try:
        geopend = os.fstat(fd)
        op_pad = pad.lstat()
        if (not stat.S_ISREG(geopend.st_mode) or stat.S_ISLNK(op_pad.st_mode)
                or (geopend.st_dev, geopend.st_ino) != (op_pad.st_dev, op_pad.st_ino)):
            raise BrugFout("Opdrachtbestand is geen gewoon bestand of is een symlink")
        if os.name == "posix" and geopend.st_uid != os.getuid():
            raise BrugFout("Opdrachtbestand is niet van de huidige gebruiker")
        if geopend.st_mode & 0o022:
            raise BrugFout("Opdrachtbestand is schrijfbaar voor anderen")
        if geopend.st_size > MAX_JSON:
            raise BrugFout("Opdrachtbestand is te groot")
        with os.fdopen(fd, "rb") as invoer:
            fd = -1
            data = invoer.read(MAX_JSON + 1)
        if len(data) > MAX_JSON:
            raise BrugFout("Opdrachtbestand is te groot")
        try:
            resultaat = json.loads(data.decode("utf-8"), object_pairs_hook=_zonder_dubbele_velden)
        except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
            raise BrugFout("Opdrachtbestand bevat geen geldige JSON") from exc
        if not isinstance(resultaat, dict):
            raise BrugFout("Opdrachtbestand moet een JSON-object zijn")
        return resultaat
    finally:
        if fd >= 0:
            os.close(fd)


def _tekstveld(waarde, naam: str, maximum: int) -> str:
    if (not isinstance(waarde, str) or not waarde or len(waarde) > maximum
            or ONVEILIGE_TEKENS.search(waarde)):
        raise BrugFout(f"Ongeldige waarde voor {naam}")
    return waarde


def _onder_thuis(pad: Path) -> bool:
    thuis = Path.home().resolve()
    return pad != thuis and pad.is_relative_to(thuis)


def valideer_opdracht(gegevens: dict, bestands_id: str) -> dict:
    if set(gegevens) != VELDEN:
        raise BrugFout("Opdracht heeft onbekende of ontbrekende velden")
    if not ID.fullmatch(bestands_id) or gegevens["id"] != bestands_id:
        raise BrugFout("Ongeldig opdracht-id")
    titel = _tekstveld(gegevens["titel"], "titel", 200)
    werk_tekst = _tekstveld(gegevens["werkmap"], "werkmap", 4096)
    rapport_tekst = _tekstveld(gegevens["rapport"], "rapport", 4096)
    werkmap = Path(werk_tekst)
    rapport = Path(rapport_tekst)
    if not werkmap.is_absolute() or not werkmap.is_dir():
        raise BrugFout("Werkmap moet een bestaande map zijn")
    if not _onder_thuis(werkmap.resolve()):
        raise BrugFout("Werkmap moet onder de thuismap liggen")
    if not rapport.is_absolute() or rapport.suffix != ".md" or rapport.is_symlink():
        raise BrugFout("Rapport moet een .md-bestand zijn, zonder symlink")
    if not _onder_thuis(rapport.resolve(strict=False)):
        raise BrugFout("Rapport moet onder de thuismap liggen")
    opdracht = gegevens["opdracht"]
    try:
        opdracht_lengte = len(opdracht.encode("utf-8")) if isinstance(opdracht, str) else 0
    except UnicodeError as exc:
        raise BrugFout("Opdrachttekst moet geldige UTF-8 zijn") from exc
    if (not isinstance(opdracht, str) or not opdracht.strip()
            or opdracht_lengte > MAX_OPDRACHT):
        raise BrugFout("Opdrachttekst is leeg of te groot (maximaal 200 kB)")
    opties = gegevens["opties"]
    if not isinstance(opties, dict) or set(opties) - OPTIES:
        raise BrugFout("Onbekende overlegoptie")
    for naam, waarde in opties.items():
        if naam in ("b", "T"):
            onder, boven = (1, 5) if naam == "b" else (1, 3600)
            if type(waarde) is not int or not onder <= waarde <= boven:
                raise BrugFout(f"Optie {naam} moet tussen {onder} en {boven} liggen")
        elif naam == "met_claude":
            if type(waarde) is not bool:
                raise BrugFout("Optie met_claude moet waar of onwaar zijn")
        elif naam in NIVEAUS:
            if not isinstance(waarde, str) or waarde not in NIVEAUS[naam]:
                raise BrugFout(f"Ongeldig denkniveau voor {naam}")
        elif not isinstance(waarde, str) or len(waarde) > 100 or not MODEL.fullmatch(waarde):
            raise BrugFout(f"Ongeldige modelnaam voor {naam}")
    return {"id": bestands_id, "werkmap": str(werkmap.resolve()),
            "rapport": str(rapport.resolve(strict=False)), "titel": titel,
            "opdracht": opdracht, "opties": opties}


def _statuspad(map_pad: Path, taak_id: str) -> Path:
    return map_pad / f"{taak_id}.status.json"


def _logpad(map_pad: Path, taak_id: str) -> Path:
    return map_pad / f"{taak_id}.log"


def _status(taak_id: str, toestand: str, **extra) -> dict:
    return {"id": taak_id, "toestand": toestand, "tijd": time.time(), **extra}


def lees_hartslag(basis: Path) -> dict | None:
    pad = basis / "hartslag.json"
    try:
        if pad.is_symlink() or pad.stat().st_size > 4096:
            return None
        gegevens = json.loads(pad.read_text(encoding="utf-8"))
        return gegevens if isinstance(gegevens, dict) else None
    except (OSError, ValueError, UnicodeError):
        return None


def brug_leeft(basis: Path) -> bool:
    slag = lees_hartslag(basis)
    if not slag or not isinstance(slag.get("laatste_tik"), (int, float)):
        return False
    if not 0 <= time.time() - slag["laatste_tik"] <= HARTSLAG_GELDIG:
        return False
    if os.name == "posix":
        try:
            os.kill(int(slag["pid"]), 0)
        except (OSError, ValueError, TypeError):
            return False
    return True


def geen_brug() -> str:
    return ("Brug draait niet of de hartslag is verlopen. Mehdi start in de Terminal "
            "van Antigravity: ~/dev/globaal-ai-debat/brug.sh")


def dien_in(args) -> int:
    basis = brugmap()
    if not brug_leeft(basis):
        raise BrugFout(geen_brug())
    maak_mappen(basis)
    try:
        if args.bestand:
            with open(args.bestand, "rb") as bron:
                invoer = bron.read(MAX_OPDRACHT + 1)
        else:
            invoer = sys.stdin.buffer.read(MAX_OPDRACHT + 1)
        opdracht = invoer.decode("utf-8")
    except UnicodeError as exc:
        raise BrugFout("Opdrachttekst moet UTF-8 zijn") from exc
    if len(invoer) > MAX_OPDRACHT:
        raise BrugFout("Opdrachttekst is te groot (maximaal 200 kB)")
    taak_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + "-" + uuid.uuid4().hex[:12]
    opties = {naam: getattr(args, naam) for naam in OPTIES if getattr(args, naam) is not None}
    gegevens = {"id": taak_id, "werkmap": str(Path(args.map).expanduser().resolve()),
                "rapport": str(Path(args.rapport).expanduser().absolute()),
                "titel": args.titel, "opdracht": opdracht, "opties": opties}
    valideer_opdracht(gegevens, taak_id)
    wachtrij = basis / "wachtrij"
    schrijf_json(_statuspad(wachtrij, taak_id), _status(taak_id, "wachtrij"))
    schrijf_json(wachtrij / f"{taak_id}.json", gegevens)
    if not args.wacht:
        print(taak_id)
        return 0
    while True:
        for naam in ("klaar", "fout"):
            pad = _statuspad(basis / naam, taak_id)
            try:
                uitkomst = json.loads(pad.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            code = uitkomst.get("exitcode", 2)
            rapport = uitkomst.get("rapport")
            if rapport:
                print(f"{taak_id}: {uitkomst['toestand']} (exitcode {code}); rapport: {rapport}")
            else:
                print(f"{taak_id}: {uitkomst['toestand']} (exitcode {code})")
            return code if isinstance(code, int) and 0 <= code <= 255 else 2
        if not brug_leeft(basis):
            raise BrugFout(geen_brug() + f" Opdracht-id: {taak_id}")
        time.sleep(0.2)


def claim_oudste(basis: Path) -> str | None:
    wachtrij = basis / "wachtrij"
    bezig = basis / "bezig"
    for pad in sorted(wachtrij.glob("*.json")):
        if pad.name.endswith(".status.json"):
            continue
        try:
            os.replace(pad, bezig / pad.name)
        except FileNotFoundError:
            continue  # Een tweede claimant was eerder.
        taak_id = pad.name[:-5]
        status_bron = _statuspad(wachtrij, taak_id)
        if status_bron.exists():
            try:
                os.replace(status_bron, _statuspad(bezig, taak_id))
            except FileNotFoundError:
                pass
        return taak_id
    return None


def _stop_procesgroep(proces: subprocess.Popen) -> bytes:
    try:
        os.killpg(proces.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    uitvoer = b""
    try:
        uitvoer, _ = proces.communicate(timeout=1)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proces.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    rest, _ = proces.communicate()
    return uitvoer + rest


def _draai(gegevens: dict, tijdslimiet: float) -> tuple[int, str, str]:
    opties = gegevens["opties"]
    overleg = Path(os.environ.get("OVERLEG_BRUG_OVERLEG") or
                   Path(__file__).resolve().with_name("overleg.sh")).resolve()
    if not overleg.is_file():
        raise BrugFout("overleg.sh ontbreekt")
    cmd = [str(overleg), "-C", gegevens["werkmap"], "-o", gegevens["rapport"],
           "-t", gegevens["titel"]]
    for naam in ("b", "m", "e", "g", "G", "c", "E", "T"):
        if naam in opties:
            cmd.extend(["-" + naam, str(opties[naam])])
    if opties.get("met_claude"):
        cmd.append("--met-claude")
    proces = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, cwd=gegevens["werkmap"],
                              env=os.environ.copy(), start_new_session=True)
    try:
        uitvoer, _ = proces.communicate(gegevens["opdracht"].encode("utf-8"), timeout=tijdslimiet)
        code = proces.returncode if proces.returncode >= 0 else 128 - proces.returncode
        return code, geheimen_weg(uitvoer.decode("utf-8", errors="replace")), ""
    except subprocess.TimeoutExpired:
        uitvoer = _stop_procesgroep(proces)
        return 124, geheimen_weg(uitvoer.decode("utf-8", errors="replace")), "Totale tijdslimiet verstreken"
    except BaseException:
        _stop_procesgroep(proces)
        raise


def verwerk(basis: Path, taak_id: str, tijdslimiet: float) -> None:
    bezig = basis / "bezig"
    job = bezig / f"{taak_id}.json"
    status = _statuspad(bezig, taak_id)
    log = _logpad(bezig, taak_id)
    rapport = None
    onderbroken = False
    try:
        gegevens = valideer_opdracht(_lees_json_veilig(job), taak_id)
        rapport = gegevens["rapport"]
        schrijf_json(status, _status(taak_id, "bezig"))
        # Paden en het opdrachtbestand worden na de claim nogmaals gecontroleerd.
        valideer_opdracht(_lees_json_veilig(job), taak_id)
        code, uitvoer, reden = _draai(gegevens, tijdslimiet)
    except KeyboardInterrupt:
        code, uitvoer, reden = 130, "", "Luisteraar onderbroken"
        onderbroken = True
    except (BrugFout, OSError, ValueError) as exc:
        code, uitvoer, reden = 2, "", geheimen_weg(str(exc))
    doel = basis / ("klaar" if code == 0 else "fout")
    schrijf_atomisch(log, geheimen_weg(uitvoer).encode("utf-8"))
    eindstatus = _status(taak_id, "klaar" if code == 0 else "fout", exitcode=code)
    if rapport:
        eindstatus["rapport"] = rapport
    if reden:
        eindstatus["reden"] = geheimen_weg(reden)
    schrijf_json(status, eindstatus)
    os.replace(job, doel / job.name)
    os.replace(log, doel / log.name)
    os.replace(status, _statuspad(doel, taak_id))
    if onderbroken:
        raise KeyboardInterrupt


def _neem_slot(basis: Path) -> int:
    pad = basis / ".luister.slot"
    fd = os.open(pad, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        geopend = os.fstat(fd)
        op_pad = pad.lstat()
        if (not stat.S_ISREG(geopend.st_mode) or stat.S_ISLNK(op_pad.st_mode)
                or (geopend.st_dev, geopend.st_ino) != (op_pad.st_dev, op_pad.st_ino)
                or geopend.st_uid != os.getuid() or geopend.st_mode & 0o022):
            raise BrugFout("Luisterslot is onveilig")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BrugFout("Er draait al een luisteraar") from exc
        return fd
    except BaseException:
        os.close(fd)
        raise


def luister(args) -> int:
    if os.name != "posix":
        raise BrugFout("De luisteraar werkt alleen op macOS en Linux")
    if not all(os.environ.get(naam, "").strip() for naam in
               ("ANTIGRAVITY_LS_ADDRESS", "ANTIGRAVITY_CSRF_TOKEN")):
        raise BrugFout("Antigravity-toegang ontbreekt; start in de Terminal van Antigravity: Terminal > New Terminal")
    basis = brugmap()
    maak_mappen(basis)
    slot = _neem_slot(basis)
    hartslag = basis / "hartslag.json"
    gestart = datetime.now(timezone.utc).isoformat()
    stop = threading.Event()

    def tik():
        while not stop.is_set():
            schrijf_json(hartslag, {"pid": os.getpid(), "starttijd": gestart,
                                  "laatste_tik": time.time(), "versie": VERSIE})
            stop.wait(HARTSLAG_INTERVAL)

    draad = threading.Thread(target=tik, daemon=True)
    try:
        tik_eenmaal = {"pid": os.getpid(), "starttijd": gestart,
                       "laatste_tik": time.time(), "versie": VERSIE}
        schrijf_json(hartslag, tik_eenmaal)
        draad.start()
        print("Brug draait, laat dit venster open", flush=True)
        while True:
            taak_id = claim_oudste(basis)
            if taak_id is not None:
                verwerk(basis, taak_id, args.tijdslimiet)
            elif args.eenmalig:
                break
            else:
                time.sleep(2)
    except KeyboardInterrupt:
        print("Brug gestopt.", flush=True)
    finally:
        stop.set()
        if draad.is_alive():
            draad.join(timeout=2)
        hartslag.unlink(missing_ok=True)
        fcntl.flock(slot, fcntl.LOCK_UN)
        os.close(slot)
    return 0


def toon_status() -> int:
    basis = brugmap()
    slag = lees_hartslag(basis)
    if brug_leeft(basis):
        print(f"Brug: actief (pid {slag['pid']}; laatste tik {datetime.fromtimestamp(slag['laatste_tik']).isoformat(timespec='seconds')})")
    else:
        print("Brug: niet actief. " + geen_brug())
    for naam in ("wachtrij", "bezig"):
        pad = basis / naam
        ids = (sorted(p.name[:-5] for p in pad.glob("*.json")
                      if ID.fullmatch(p.name[:-5])) if pad.is_dir() else [])
        print(f"{naam.capitalize()}: {len(ids)}" + (" (" + ", ".join(ids) + ")" if ids else ""))
    uitkomsten = []
    for naam in ("klaar", "fout"):
        pad = basis / naam
        if pad.is_dir():
            for status in pad.glob("*.status.json"):
                try:
                    if status.is_symlink() or status.stat().st_size > 4096:
                        continue
                    data = json.loads(status.read_text(encoding="utf-8"))
                    if (isinstance(data, dict) and type(data.get("tijd")) in (int, float)
                            and isinstance(data.get("id"), str)
                            and ID.fullmatch(data["id"])):
                        uitkomsten.append((data["tijd"], data["id"], naam, data.get("exitcode")))
                except (OSError, ValueError, KeyError, TypeError):
                    pass
    print("Laatste uitkomsten:")
    for _, taak_id, naam, code in sorted(uitkomsten, reverse=True)[:5]:
        print(f"  {geheimen_weg(str(taak_id))}: {naam} (exitcode {code})")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Lokale brug naar read-only driehoeksoverleg")
    sub = parser.add_subparsers(dest="actie", required=True)
    luister_p = sub.add_parser("luister", help="verwerk opdrachten vanuit de Terminal van Antigravity")
    luister_p.add_argument("--eenmalig", action="store_true", help="verwerk de huidige wachtrij en stop")
    luister_p.add_argument("--tijdslimiet", type=float, default=STANDAARD_TIJD_LIMIET,
                           help="totale tijdslimiet per opdracht in seconden (standaard 10800)")
    indien_p = sub.add_parser("indienen", help="zet een overleg in de wachtrij")
    indien_p.add_argument("-C", "--map", required=True)
    indien_p.add_argument("-o", "--rapport", required=True)
    indien_p.add_argument("-t", "--titel", required=True)
    indien_p.add_argument("--bestand", help="lees de opdrachttekst uit dit bestand; anders stdin")
    indien_p.add_argument("--wacht", action="store_true")
    for optie in ("b", "m", "e", "g", "G", "c", "E", "T"):
        indien_p.add_argument("-" + optie, dest=optie, type=int if optie in ("b", "T") else str)
    indien_p.add_argument("--met-claude", dest="met_claude", action="store_true", default=None)
    sub.add_parser("status", help="toon hartslag, wachtrij en laatste uitkomsten")
    args = parser.parse_args(argv)
    try:
        if args.actie == "luister":
            if not 0 < args.tijdslimiet <= STANDAARD_TIJD_LIMIET:
                raise BrugFout("Tijdslimiet moet tussen 0 en 10800 seconden liggen")
            return luister(args)
        if args.actie == "indienen":
            return dien_in(args)
        return toon_status()
    except (BrugFout, OSError) as exc:
        print("brug.py: " + geheimen_weg(str(exc)), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
