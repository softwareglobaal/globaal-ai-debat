"""Lokale wachtrij voor read-only overleg vanuit de Terminal van Antigravity.

De luisteraar is het enige proces dat de Antigravity-omgeving erft. Opdrachten,
statussen en logs bevatten uitsluitend taakgegevens en gezuiverde uitvoer.
"""

import argparse
import http.client
import json
import math
import os
import re
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid
from urllib import error as urlerror, request as urlrequest
from datetime import datetime, timezone
from pathlib import Path

if os.name == "posix":
    import fcntl


VERSIE = 2
VEROUDERD = 3
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


class SlotBezet(BrugFout):
    """Het bestaande luisterslot wordt al door een andere luisteraar gehouden."""


def brugmap() -> Path:
    return Path(os.environ.get("OVERLEG_BRUG_MAP") or Path.home() / ".overleg-brug").expanduser()


def geheimen_weg(tekst: str) -> str:
    for naam in ("ANTIGRAVITY_CSRF_TOKEN", "ANTIGRAVITY_LS_ADDRESS"):
        waarde = os.environ.get(naam, "")
        for geheim in sorted({waarde, waarde.strip()}, key=len, reverse=True):
            if geheim:
                tekst = tekst.replace(geheim, "[afgeschermd]")
                tekst = tekst.replace(json.dumps(geheim, ensure_ascii=True)[1:-1], "[afgeschermd]")
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


def _levend(gegevens: dict | None) -> bool:
    if not gegevens or type(gegevens.get("laatste_tik")) not in (int, float):
        return False
    if not 0 <= time.time() - gegevens["laatste_tik"] <= HARTSLAG_GELDIG:
        return False
    if os.name == "posix":
        try:
            pid = gegevens["pid"]
            if type(pid) is not int or pid <= 0:
                return False
            os.kill(pid, 0)
        except (OSError, ValueError, TypeError):
            return False
    return True


def lees_reserves(basis: Path) -> list[dict]:
    """Iedere reserve heeft een eigen bestand, zodat gelijktijdige reserves elkaar niet overschrijven."""
    reserves = []
    for pad in basis.glob("reserve.*.json"):
        try:
            if pad.is_symlink() or pad.stat().st_size > 4096:
                continue
            gegevens = json.loads(pad.read_text(encoding="utf-8"))
            if (isinstance(gegevens, dict) and _levend(gegevens)
                    and _reserveproces_actief(gegevens["pid"])):
                reserves.append(gegevens)
        except (OSError, ValueError, UnicodeError):
            continue
    return reserves


def _reserveproces_actief(pid: int) -> bool:
    """`kill(pid, 0)` ziet ook een zombie; die kan het slot nooit overnemen."""
    if os.name != "posix":
        return True
    try:
        controle = subprocess.run(
            ["/bin/ps", "-o", "stat=", "-p", str(pid)], capture_output=True,
            text=True, timeout=1, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
    except (OSError, subprocess.TimeoutExpired):
        return True  # De geldige tik en kill(pid, 0) blijven de terugval.
    status = controle.stdout.strip()
    return controle.returncode == 0 and bool(status) and status[0] != "Z"


def brug_leeft(basis: Path) -> bool:
    return _levend(lees_hartslag(basis)) or bool(lees_reserves(basis))


def geen_brug() -> str:
    return ("Brug draait niet of de hartslag is verlopen. Draai eenmalig "
            "~/dev/globaal-ai-debat/installeer_sidecar.sh en zet 'overleg-brug' aan "
            "in Antigravity: Automations; of start ~/dev/globaal-ai-debat/brug.sh "
            "in de Terminal van Antigravity.")


def lokaal_adres(adres: str) -> bool:
    """Alleen een expliciete loopback-host met poort mag het token ontvangen."""
    if not re.fullmatch(r"(?:127\.0\.0\.1|localhost|\[::1\]):[0-9]{1,5}",
                        adres, re.ASCII | re.IGNORECASE):
        return False
    return 1 <= int(adres.rsplit(":", 1)[1]) <= 65535


def toegang(adres: str, token: str, timeout: float = 3) -> str:
    """Toets bereikbaarheid via Heartbeat, zonder antwoord of toegangsgegevens te bewaren."""
    try:
        if not lokaal_adres(adres):
            return "weg"
        url = "http://" + adres + "/exa.language_server_pb.LanguageServerService/Heartbeat"
        verzoek = urlrequest.Request(
            url, data=b"{}", method="POST",
            headers={"Content-Type": "application/json", "x-codeium-csrf-token": token})
        # Een lokale Language Server hoort nooit via een ingestelde HTTP-proxy te gaan.
        class GeenOmleiding(urlrequest.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        opener = urlrequest.build_opener(urlrequest.ProxyHandler({}), GeenOmleiding())
        with opener.open(verzoek, timeout=timeout):
            return "ok"
    except urlerror.HTTPError as exc:
        exc.close()
        if 300 <= exc.code < 400:
            return "weg"
        return "geweigerd" if exc.code in (401, 403) else "ok"
    except (OSError, ValueError, http.client.HTTPException):
        return "weg"


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
    zonder_brug_sinds = None
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
        if brug_leeft(basis):
            zonder_brug_sinds = None
        else:
            # Alleen een taak die nog werkelijk in de wachtrij ligt mag worden ingetrokken.
            # De verplaatsing van het opdrachtbestand beslist atomisch wie eigenaar is.
            job = wachtrij / f"{taak_id}.json"
            doel = basis / "fout"
            try:
                os.replace(job, doel / job.name)
            except FileNotFoundError:
                # De luisteraar heeft haar al geclaimd. Wacht op de eindstatus,
                # ook tijdens een korte overdracht naar een reserve.
                if os.name == "posix":
                    try:
                        slot = _neem_slot(basis)
                    except SlotBezet:
                        pass
                    else:
                        try:
                            herstel_verweesde_taken(basis)
                        finally:
                            fcntl.flock(slot, fcntl.LOCK_UN)
                            os.close(slot)
                if zonder_brug_sinds is None:
                    zonder_brug_sinds = time.monotonic()
                elif time.monotonic() - zonder_brug_sinds >= 120:
                    raise BrugFout(geen_brug() + f" Opdracht-id: {taak_id}")
            else:
                _statuspad(wachtrij, taak_id).unlink(missing_ok=True)
                schrijf_json(_statuspad(doel, taak_id), _status(
                    taak_id, "fout", exitcode=2, reden="Ingetrokken: brug draait niet"))
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


def _leider_klaar(proces: subprocess.Popen) -> bool:
    """Is de leider gestopt? Zonder op te ruimen (WNOWAIT): zolang hij als zombie
    bestaat, blijft zijn groepsnummer bezet en kan het niet aan een ander proces gaan."""
    try:
        return os.waitid(os.P_PID, proces.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
    except ChildProcessError:
        return True


def _stop_procesgroep(proces: subprocess.Popen) -> bytes:
    # Een al opgeruimde leider heeft zijn groepsnummer vrijgegeven: dan geen signaal meer.
    if proces.returncode is None:
        try:
            os.killpg(proces.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass  # macOS geeft EPERM voor een groep met alleen nog de zombie-leider.
        einde = time.monotonic() + 7
        while not _leider_klaar(proces) and time.monotonic() < einde:
            time.sleep(0.05)
        # De leider is nog niet opgeruimd, dus deze SIGKILL raakt alleen zijn eigen groep:
        # achtergebleven kinderen van het overleg, nooit een proces met een hergebruikt nummer.
        try:
            os.killpg(proces.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    # Pas nu opruimen; communicate geeft ook de eerder gelezen uitvoer terug.
    try:
        uitvoer, _ = proces.communicate(timeout=1)
    except subprocess.TimeoutExpired as exc:
        # Een eigenzinnig kleinkind kan een geërfde uitvoerpijp openhouden.
        # De overlegouder is gedood; blijf hier nooit onbeperkt op die pijp wachten,
        # maar bewaar wat al gelezen was voor de foutlog.
        if proces.stdout is not None:
            proces.stdout.close()
        proces.wait(timeout=1)
        uitvoer = exc.output or b""
    return uitvoer or b""


def herstel_verweesde_taken(basis: Path) -> None:
    """Een nieuw slot bewijst dat geen vorige luisteraar nog een taak kan afmaken."""
    bezig = basis / "bezig"
    fout = basis / "fout"
    ids = {pad.name[:-5] for pad in bezig.glob("*.json")
           if ID.fullmatch(pad.name[:-5])}
    ids.update(pad.name[:-12] for pad in bezig.glob("*.status.json")
               if ID.fullmatch(pad.name[:-12]))
    for taak_id in sorted(ids):
        job = bezig / f"{taak_id}.json"
        status = _statuspad(bezig, taak_id)
        log = _logpad(bezig, taak_id)
        _statuspad(basis / "wachtrij", taak_id).unlink(missing_ok=True)
        try:
            bewaard = _lees_json_veilig(status)
        except (BrugFout, OSError):
            bewaard = {}
        if (bewaard.get("id") == taak_id
                and bewaard.get("toestand") in ("klaar", "fout")
                and type(bewaard.get("exitcode")) is int):
            doel = basis / bewaard["toestand"]
            if job.exists():
                os.replace(job, doel / job.name)
            if log.exists():
                os.replace(log, _logpad(doel, taak_id))
            os.replace(status, _statuspad(doel, taak_id))
            continue
        if not job.exists() and status.exists():
            # Een vorige luisteraar kan al het opdrachtbestand hebben verplaatst,
            # maar zijn laatste status nog niet. Maak die overgang alsnog af.
            for naam in ("klaar", "fout"):
                doel = basis / naam
                if (doel / job.name).exists():
                    if log.exists():
                        os.replace(log, _logpad(doel, taak_id))
                    os.replace(status, _statuspad(doel, taak_id))
                    break
            else:
                schrijf_json(_statuspad(fout, taak_id), _status(
                    taak_id, "fout", exitcode=3,
                    reden="Afgebroken: vorige luisteraar stopte"))
                status.unlink(missing_ok=True)
            continue
        eindstatus = _status(taak_id, "fout", exitcode=3,
                             reden="Afgebroken: vorige luisteraar stopte")
        os.replace(job, fout / job.name)
        if log.exists():
            os.replace(log, _logpad(fout, taak_id))
        schrijf_json(_statuspad(fout, taak_id), eindstatus)
        status.unlink(missing_ok=True)


def _draai(gegevens: dict, tijdslimiet: float,
           annuleer: threading.Event | None = None,
           stop: threading.Event | None = None) -> tuple[int, str, str]:
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
    if stop is not None and stop.is_set():
        return 130, "", "Luisteraar gestopt"
    proces = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, cwd=gegevens["werkmap"],
                              env=os.environ.copy(), start_new_session=True)
    try:
        einde = time.monotonic() + tijdslimiet
        invoer = gegevens["opdracht"].encode("utf-8")
        while True:
            if stop is not None and stop.is_set():
                uitvoer = _stop_procesgroep(proces)
                return 130, geheimen_weg(uitvoer.decode("utf-8", errors="replace")), "Luisteraar gestopt"
            if annuleer is not None and annuleer.is_set():
                uitvoer = _stop_procesgroep(proces)
                return VEROUDERD, geheimen_weg(uitvoer.decode("utf-8", errors="replace")), "Luisteraar verouderd"
            resterend = einde - time.monotonic()
            if resterend <= 0:
                uitvoer = _stop_procesgroep(proces)
                return 124, geheimen_weg(uitvoer.decode("utf-8", errors="replace")), "Totale tijdslimiet verstreken"
            try:
                uitvoer, _ = proces.communicate(invoer, timeout=min(0.2, resterend))
                code = proces.returncode if proces.returncode >= 0 else 128 - proces.returncode
                return code, geheimen_weg(uitvoer.decode("utf-8", errors="replace")), ""
            except subprocess.TimeoutExpired:
                invoer = None
    except BaseException:
        _stop_procesgroep(proces)
        raise


def verwerk(basis: Path, taak_id: str, tijdslimiet: float,
           annuleer: threading.Event | None = None,
           stop: threading.Event | None = None) -> None:
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
        code, uitvoer, reden = _draai(gegevens, tijdslimiet, annuleer, stop)
    except KeyboardInterrupt:
        code, uitvoer, reden = 130, "", "Luisteraar gestopt"
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
            raise SlotBezet("Er draait al een luisteraar") from exc
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
    ouder = os.getppid()
    adres = os.environ["ANTIGRAVITY_LS_ADDRESS"].strip()
    token = os.environ["ANTIGRAVITY_CSRF_TOKEN"].strip()
    eerste = toegang(adres, token)
    if eerste == "weg":
        print("Antigravity-gegevens van deze luisteraar kloppen niet meer (Antigravity herstart?); luisteraar stopt",
              file=sys.stderr, flush=True)
        return VEROUDERD
    alleen_bereikbaarheid = eerste == "geweigerd"
    if alleen_bereikbaarheid:
        print("Heartbeat gaf geweigerd bij de start; alleen bereikbaarheid wordt bewaakt",
              file=sys.stderr, flush=True)

    basis = brugmap()
    maak_mappen(basis)
    hartslag = basis / "hartslag.json"
    gestart = datetime.now(timezone.utc).isoformat()
    stop = threading.Event()
    annuleer = threading.Event()
    ouder_weg = threading.Event()
    meting_slot = threading.Lock()
    toestand = {"laatste_slecht": False, "laatste_goed": time.monotonic(),
                "laatste_meting": time.monotonic(), "slechte_reeks": 0}
    slot = None
    eigenaar = False
    reservepad = basis / f"reserve.{os.getpid()}.json"
    oude_signalen = {}
    stop_signaal_bezig = False

    def stop_signaal(nummer, _frame):
        nonlocal stop_signaal_bezig
        if stop_signaal_bezig:
            return
        stop_signaal_bezig = True
        # Een tweede stopsignaal mag de statusverplaatsing niet onderbreken.
        for stopnummer in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(stopnummer, signal.SIG_IGN)
        stop.set()

    if threading.current_thread() is threading.main_thread():
        for nummer in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            oude_signalen[nummer] = signal.signal(nummer, stop_signaal)

    def meet():
        with meting_slot:
            uitkomst = toegang(adres, token)
            toestand["laatste_meting"] = time.monotonic()
            slecht = uitkomst == "weg" or (uitkomst == "geweigerd" and not alleen_bereikbaarheid)
            toestand["laatste_slecht"] = slecht
            if slecht:
                toestand["slechte_reeks"] += 1
                if toestand["slechte_reeks"] >= 3:
                    annuleer.set()
            else:
                toestand["slechte_reeks"] = 0
                toestand["laatste_goed"] = time.monotonic()

    def bewaak():
        volgende = time.monotonic() + args.toegang_interval
        while not stop.is_set() and not annuleer.is_set():
            if args.ouder_bewaken and os.getppid() != ouder:
                ouder_weg.set()
                annuleer.set()
                break
            nu = time.monotonic()
            if nu >= volgende:
                meet()
                volgende = time.monotonic() + args.toegang_interval
            stop.wait(min(0.1, max(0, volgende - time.monotonic())))

    bewaker = threading.Thread(target=bewaak, daemon=True)

    def verouderd_bericht():
        if ouder_weg.is_set():
            print("Antigravity is gestopt; luisteraar stopt", file=sys.stderr, flush=True)
        else:
            print("Antigravity-gegevens van deze luisteraar kloppen niet meer (Antigravity herstart?); luisteraar stopt",
                  file=sys.stderr, flush=True)
        return VEROUDERD

    def tik():
        while not stop.is_set():
            schrijf_json(hartslag, {"pid": os.getpid(), "starttijd": gestart,
                                  "laatste_tik": time.time(), "versie": VERSIE,
                                  "bron": bron})
            stop.wait(HARTSLAG_INTERVAL)

    bron = ("sidecar" if ("ANTIGRAVITY_SIDECAR_WEB_PORT" in os.environ or
                         "ANTIGRAVITY_EXECUTABLE_DATA_DIR" in os.environ) else "terminal")
    draad = threading.Thread(target=tik, daemon=True)
    try:
        bewaker.start()
        volgend_slot = 0.0
        volgende_reservetik = 0.0
        reserve_gemeld = False
        while slot is None:
            if stop.is_set():
                break
            if annuleer.is_set():
                return verouderd_bericht()
            if time.monotonic() >= volgend_slot:
                try:
                    slot = _neem_slot(basis)
                except SlotBezet:
                    if not args.wacht_op_slot:
                        raise
                    # Slot elke 0,5 s proberen, maar de reservetik (met fsync) zoals de hartslag elke 5 s.
                    if time.monotonic() >= volgende_reservetik:
                        schrijf_json(reservepad, {"pid": os.getpid(), "starttijd": gestart,
                                                   "laatste_tik": time.time(), "versie": VERSIE,
                                                   "bron": bron})
                        volgende_reservetik = time.monotonic() + HARTSLAG_INTERVAL
                    if not reserve_gemeld:
                        print("Er draait al een luisteraar; deze wacht als reserve", flush=True)
                        reserve_gemeld = True
                    volgend_slot = time.monotonic() + 0.5
            if slot is None:
                stop.wait(0.1)
        if stop.is_set():
            print("Brug gestopt.", flush=True)
            return 0
        if annuleer.is_set():
            return verouderd_bericht()
        eigenaar = True
        tik_eenmaal = {"pid": os.getpid(), "starttijd": gestart,
                       "laatste_tik": time.time(), "versie": VERSIE, "bron": bron}
        schrijf_json(hartslag, tik_eenmaal)
        reservepad.unlink(missing_ok=True)
        herstel_verweesde_taken(basis)
        draad.start()
        print("Brug draait, laat dit venster open", flush=True)
        while True:
            if stop.is_set():
                break
            if annuleer.is_set():
                return verouderd_bericht()
            taak_id = None
            wachtende_taak = any(not p.name.endswith(".status.json")
                                for p in (basis / "wachtrij").glob("*.json"))
            if wachtende_taak:
                with meting_slot:
                    moet_meten = (time.monotonic() - toestand["laatste_meting"] >=
                                  (1 if toestand["laatste_slecht"] else 10))
                if moet_meten:
                    meet()
                with meting_slot:
                    if (not toestand["laatste_slecht"] and not annuleer.is_set()
                            and not stop.is_set()):
                        taak_id = claim_oudste(basis)
            if taak_id is not None:
                verwerk(basis, taak_id, args.tijdslimiet, annuleer, stop)
            elif args.eenmalig:
                if annuleer.is_set():
                    return verouderd_bericht()
                if wachtende_taak:
                    stop.wait(0.1)
                    continue
                break
            else:
                stop.wait(0.1)
        if stop.is_set():
            print("Brug gestopt.", flush=True)
    except KeyboardInterrupt:
        print("Brug gestopt.", flush=True)
    finally:
        stop.set()
        if bewaker.is_alive():
            bewaker.join(timeout=4)
        if draad.is_alive():
            draad.join(timeout=2)
        if eigenaar:
            hartslag.unlink(missing_ok=True)
        reservepad.unlink(missing_ok=True)
        if slot is not None:
            fcntl.flock(slot, fcntl.LOCK_UN)
            os.close(slot)
        for nummer, vorige in oude_signalen.items():
            signal.signal(nummer, vorige)
    return 0


def toon_status() -> int:
    basis = brugmap()
    slag = lees_hartslag(basis)
    if _levend(slag):
        print(f"Brug: actief (pid {slag['pid']}; bron {slag.get('bron', 'onbekend')}; laatste tik {datetime.fromtimestamp(slag['laatste_tik']).isoformat(timespec='seconds')})")
    elif lees_reserves(basis):
        print("Brug: reserve staat klaar")
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
    luister_p.add_argument("--wacht-op-slot", action="store_true", help="wacht als reserve tot het luisterslot vrijkomt")
    luister_p.add_argument("--ouder-bewaken", action="store_true", help="stop als het startende Antigravity-proces weg is")
    luister_p.add_argument("--toegang-interval", type=float, default=30,
                           help="seconden tussen toegangstoetsen (standaard 30)")
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
            if not math.isfinite(args.toegang_interval) or not 0.2 <= args.toegang_interval <= 600:
                raise BrugFout("Toegang-interval moet tussen 0.2 en 600 seconden liggen")
            return luister(args)
        if args.actie == "indienen":
            return dien_in(args)
        return toon_status()
    except (BrugFout, OSError) as exc:
        print("brug.py: " + geheimen_weg(str(exc)), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
