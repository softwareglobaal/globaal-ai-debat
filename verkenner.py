"""Maakt een briefing van een projectmap voor gebruik als debatcontext.

Werkwijze: eerst deterministisch verzamelen wat veilig is, dan de Claude-kant
lokaal een leesbare samenvatting laten schrijven. Die stap blijft op deze machine,
dus het rondkijken zelf lekt niets. Wat er uiteindelijk naar OpenAI gaat is de
briefing die jij daarna goedkeurt.
"""

import fnmatch
import re
from pathlib import Path

import debat

# Mappen die nooit worden ingelezen.
MAP_OVERSLAAN = {
    ".git", ".svn", "node_modules", "__pycache__", ".venv", "venv", "env",
    "dist", "build", ".next", ".cache", "target", ".pytest_cache", ".mypy_cache",
    "site-packages", ".idea", ".vscode", "coverage", ".terraform",
}

# Bestanden die geheimen kunnen bevatten. Nooit inlezen, wel melden.
GEHEIM_PATRONEN = [
    ".env", ".env.*", "*.env", "*.pem", "*.key", "*.pfx", "*.p12", "*.ppk",
    "id_rsa*", "id_ed25519*", "*.keystore", "*.jks",
    "*credential*", "*secret*", "*password*", "*wachtwoord*", "*token*",
    "*.kdbx", ".npmrc", ".pypirc", ".netrc", "auth.json",
]

# Alleen deze extensies worden als tekst ingelezen.
TEKST_EXTENSIES = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".rb", ".php",
    ".sh", ".ps1", ".sql", ".html", ".css", ".scss", ".md", ".txt", ".rst",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".xml",
    ".dockerfile", ".tf", ".gradle", ".vue", ".svelte",
}

# Bestanden die bovenaan de aandachtslijst staan.
KERNBESTANDEN = [
    "README.md", "readme.md", "README", "package.json", "pyproject.toml",
    "requirements.txt", "docker-compose.yml", "docker-compose.yaml",
    "Dockerfile", "Makefile", "CLAUDE.md", "go.mod", "Cargo.toml", "pom.xml",
]

MAX_BESTAND = 12000      # tekens per bestand in het ruwe materiaal
MAX_MATERIAAL = 150000   # tekens totaal aan ruw materiaal (blijft lokaal)
MAX_BESTANDEN = 60       # aantal bestanden waarvan inhoud meegaat


def is_geheim(naam: str) -> bool:
    laag = naam.lower()
    return any(fnmatch.fnmatch(laag, p) for p in GEHEIM_PATRONEN)


def loop_map(wortel: Path):
    """Levert (pad, reden_overgeslagen). Reden is None als het bestand meetelt."""
    for pad in sorted(wortel.rglob("*")):
        delen = set(pad.relative_to(wortel).parts)
        if delen & MAP_OVERSLAAN:
            continue
        if pad.is_dir():
            continue
        if is_geheim(pad.name):
            yield pad, "kan geheimen bevatten"
            continue
        try:
            grootte = pad.stat().st_size
        except OSError:
            yield pad, "niet leesbaar"
            continue
        if grootte > 400_000:
            yield pad, f"te groot ({grootte // 1024} kB)"
            continue
        if pad.suffix.lower() not in TEKST_EXTENSIES and pad.name not in KERNBESTANDEN:
            yield pad, "geen tekstbestand"
            continue
        yield pad, None


def genegeerd_door_git(wortel: Path, paden: list) -> set:
    """Vraagt git welke paden genegeerd zijn. Is het geen repo, dan valt dit stil
    terug op een lege verzameling en doet alleen MAP_OVERSLAAN het werk."""
    if not paden or not (wortel / ".git").exists():
        return set()
    git = debat.shutil.which("git")
    if not git:
        return set()
    invoer = "\n".join(str(p.relative_to(wortel)) for p in paden)
    r = debat.subprocess.run(
        [git, "check-ignore", "--stdin"], input=invoer, capture_output=True,
        text=True, encoding="utf-8", errors="replace", cwd=str(wortel))
    return {regel.strip().replace("/", "\\") for regel in r.stdout.splitlines() if regel.strip()}


def verzamel(wortel: Path) -> dict:
    """Bouwt het ruwe materiaal plus een verantwoording van wat is overgeslagen."""
    kandidaten = [pad for pad, reden in loop_map(wortel) if reden is None]
    genegeerd = genegeerd_door_git(wortel, kandidaten)

    meetellend, overgeslagen, per_extensie = [], [], {}
    for pad, reden in loop_map(wortel):
        relatief = str(pad.relative_to(wortel))
        if reden is None and relatief in genegeerd:
            reden = "staat in .gitignore"
        if reden:
            overgeslagen.append({"bestand": relatief, "reden": reden})
            continue
        meetellend.append(pad)
        ext = pad.suffix.lower() or "(geen)"
        per_extensie[ext] = per_extensie.get(ext, 0) + 1

    # Kernbestanden eerst, daarna de grootste bronbestanden.
    groottes = {p: p.stat().st_size for p in meetellend}
    gekozen = sorted(meetellend,
                     key=lambda p: (0 if p.name in KERNBESTANDEN else 1, -groottes[p])
                     )[:MAX_BESTANDEN]

    stukken, totaal = [], 0
    for pad in gekozen:
        if totaal >= MAX_MATERIAAL:
            overgeslagen.append({"bestand": str(pad.relative_to(wortel)),
                                 "reden": "materiaalbudget vol"})
            continue
        try:
            inhoud = pad.read_text(encoding="utf-8", errors="replace")
        except OSError:
            overgeslagen.append({"bestand": str(pad.relative_to(wortel)), "reden": "niet leesbaar"})
            continue
        afgekapt = len(inhoud) > MAX_BESTAND
        inhoud = inhoud[:MAX_BESTAND]
        kop = f"--- {pad.relative_to(wortel)}" + (" (afgekapt)" if afgekapt else "") + " ---"
        stukken.append(f"{kop}\n{inhoud}")
        totaal += len(inhoud)

    boom = "\n".join(sorted(str(p.relative_to(wortel)) for p in meetellend)[:400])
    samenvatting = ", ".join(f"{ext}: {n}" for ext, n in
                             sorted(per_extensie.items(), key=lambda x: -x[1])[:15])

    materiaal = (
        f"PROJECTMAP: {wortel.name}\n"
        f"AANTAL BESTANDEN: {len(meetellend)}\n"
        f"PER TYPE: {samenvatting}\n\n"
        f"BESTANDEN:\n{boom}\n\n"
        f"INHOUD VAN DE BELANGRIJKSTE BESTANDEN:\n\n" + "\n\n".join(stukken)
    )
    return {
        "materiaal": materiaal,
        "meegenomen": [str(p.relative_to(wortel)) for p in gekozen],
        "overgeslagen": overgeslagen,
        "aantal_bestanden": len(meetellend),
    }


OPDRACHT = """Je schrijft een feitelijke briefing over een codebase. Die briefing wordt
straks gelezen door twee AI-modellen die er een inhoudelijke discussie over voeren, en
door de eigenaar van de code.

Eisen:
- Maximaal {woorden} woorden.
- Beschrijf: waar het project voor dient, de stack, de structuur, hoe het draait en
  wordt uitgerold, de belangrijkste onderdelen en hun onderlinge afhankelijkheden.
- Noem concrete cijfers waar je die ziet: aantallen bestanden, tabellen, endpoints, apps.
- Benoem opvallende zwakke plekken die je in de code ziet, feitelijk en zonder advies.
- Geen aanbevelingen, geen oordeel, geen inleiding of afsluiting.
- Neem NOOIT letterlijk over: sleutels, wachtwoorden, tokens, verbindingsreeksen,
  e-mailadressen, persoonsnamen, IP-adressen of hostnamen. Kom je die tegen, schrijf dan
  alleen dat ze er staan en waar, zonder de waarde. Schrijf dus "een e-mailadres van een
  medewerker", niet het adres zelf.
- Schrijf in het Nederlands. Geen em dash, geen emoji.
"""


# Patronen die niet in een briefing thuishoren. Sleutels zijn de melding.
CONTROLES = [
    ("e-mailadres", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    ("IP-adres", r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    ("hostnaam", r"\b[a-z0-9-]+\.(?:globaal\.be|elevaitnv\.com|angela\.sr)\b"),
    ("verbindingsreeks", r"[a-z]+://[^\s:@/]+:[^\s@/]+@\S+"),
    ("sleutel of token", r"\b(?:sk-|pk-|ghp_|gho_|xox[baprs]-|AKIA)[A-Za-z0-9_\-]{8,}"),
    ("lange geheimachtige tekenreeks", r"\b[A-Za-z0-9+/=_-]{40,}\b"),
]


def masker(waarde: str) -> str:
    """Toon genoeg om het te herkennen, nooit genoeg om het te gebruiken."""
    return waarde[:3] + "*" * max(4, min(12, len(waarde) - 3))


def controleer_briefing(tekst: str) -> list:
    """Zoekt in de briefing naar dingen die je niet naar buiten wilt sturen.

    Dit verwijdert niets: jij beslist. Het zorgt alleen dat je het ziet voor je
    op starten drukt.
    """
    gevonden = []
    for melding, patroon in CONTROLES:
        for tref in dict.fromkeys(re.findall(patroon, tekst)):
            gevonden.append({"soort": melding, "gemaskeerd": masker(tref)})
    return gevonden


def maak_briefing(map_pad: str, woorden: int = 500, model: str = "sonnet",
                  timeout: int = 600, registreer=None) -> dict:
    wortel = Path(map_pad).resolve()
    if not wortel.is_dir():
        raise ValueError(f"{wortel} is geen map")

    verzameld = verzamel(wortel)
    if not verzameld["aantal_bestanden"]:
        raise ValueError("geen leesbare bestanden gevonden in deze map")

    # Deze aanroep draait lokaal op het Claude-abonnement en stuurt niets naar OpenAI.
    briefing = debat.roep_claude(
        OPDRACHT.format(woorden=woorden),
        verzameld["materiaal"],
        model,
        timeout,
        registreer,
    )
    return {
        "briefing": briefing,
        "waarschuwingen": controleer_briefing(briefing),
        "projectmap": str(wortel),
        "meegenomen": verzameld["meegenomen"],
        "overgeslagen": verzameld["overgeslagen"],
        "aantal_bestanden": verzameld["aantal_bestanden"],
    }
