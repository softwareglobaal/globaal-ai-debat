"""Driehoeksoverleg tussen Claude (maker/architect), Codex (controleur/randgevallen) en Gemini (systeemdenker/architectuur).

Wordt aangeroepen via overleg.sh (en ~/.claude/tools/overleg.sh):
    overleg.sh -C <map> -o <rapport.md> [-t "<titel>"] [-b <rondes>] [-T <seconden>] < opdracht.md
    overleg.sh --verwerking <rapport.md> < verwerkt.md
    overleg.sh --zelftest

Hoe het werkt:
1. Claude zet het vraagstuk of de controle-opdracht in het dashboard (beurt 1: OPDRACHT).
2. In ronde 1 analyseren Codex en Gemini de vraag en de code in <map> (alleen lezend).
   Ze vullen elkaars blinde vlekken aan: Gemini leest ook Codex' bevindingen en reageert daar direct op.
3. In vervolgrondes (standaard 1 kruisronde, instelbaar met -b) reageert Codex op Gemini's aanvullingen en kritiek,
   en formuleert Gemini of Codex de gezamenlijke synthese: waar zijn we het over eens, welke valse meldingen vallen af,
   en wat is het concrete uitvoerplan voor Claude.
4. Het gezamenlijke eindadvies komt in <rapport.md> en op stdout (voor Claude Code), en elke beurt staat live in het
   dashboard van ai-debat (http://127.0.0.1:8099).
"""

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import debat
import ronde

SYSTEEM_OVERLEG = """Je neemt deel aan een driehoeksoverleg tussen Claude, Codex (ChatGPT) en Gemini voor Mehdi Chegini.

Doel en toon (HARDE REGEL VAN MEHDI):
- Mehdi leest mee in het dashboard. Hij wil GEEN technisch jargon, geen lange lappen tekst en geen blabla.
- Schrijf KORT, BONDIG en in GEWONE MENSENTAAL (alles samen maximaal 1 A4, ca. 350-450 woorden per beurt).
- Leg elk punt uit aan de hand van wat Mehdi in de praktijk merkt (bijv. "Als je twee afspraken tegelijk hebt, word je voor de tweede niet gebeld"), niet in codetaal.
- Onderaan elk punt zet je op één korte regel voor Claude/Shaniel de technische vindplaats en fix (`Techniek voor Claude: bestand:regel — fix`).
- Het maakt NIET uit wie gelijk heeft; alleen het resultaat voor het project telt. Vul elkaars blinde vlekken aan en corrigeer fouten direct.
- Alleen lezen: wijzig geen bestanden, maak geen commits, raak geen live systemen, mail of agenda aan.
- Nederlands. Geen emoji, geen em dash. Beslissing altijd op de eerste regel.
"""


def _codex_config(sleutel: str) -> str:
    cfg = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml"
    if not cfg.is_file():
        return ""
    for regel in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
        s = regel.strip()
        if s.startswith("["):
            break
        if s.startswith(sleutel) and "=" in s:
            k, _, v = s.partition("=")
            if k.strip() == sleutel:
                return v.strip().strip('"').strip("'")
    return ""


def roep_codex_in_map(werkmap: Path, prompt: str, model: str, niveau: str, timeout: int) -> str:
    codex_bin = os.environ.get("CODEX_BIN", "/opt/homebrew/bin/codex")
    if not Path(codex_bin).is_file():
        codex_bin = debat.vind("codex")
    with tempfile.TemporaryDirectory() as tmp:
        uit_pad = Path(tmp) / "antwoord.md"
        cmd = [
            codex_bin, "exec", "--ephemeral", "--skip-git-repo-check",
            "-s", "read-only", "-C", str(werkmap), "-o", str(uit_pad),
            "--ignore-user-config", "--disable", "apps", "--disable", "plugins",
        ]
        if model:
            cmd += ["-m", model]
        if niveau:
            cmd += ["-c", f'model_reasoning_effort="{niveau}"']
        cmd += ["-"]
        code, uit, fout = debat._draai(cmd, prompt, timeout, None, werkmap)
        if code != 0:
            raise RuntimeError(f"Codex stopte met code {code}: {(fout.strip() or uit.strip())[-500:]}")
        if uit_pad.is_file():
            tekst = uit_pad.read_text(encoding="utf-8", errors="replace").strip()
            if tekst:
                return tekst
        return debat.schoon_codex(uit)


def bouw_overleg_prompt(opdracht_tekst: str, geschiedenis: list, spreker: str, is_slot: bool) -> str:
    delen = [
        "OPDRACHT EN VRAAGSTUK (van Claude / Mehdi)",
        opdracht_tekst.strip(),
        "",
    ]
    if geschiedenis:
        delen.append("HET OVERLEG TOT NU TOE")
        for b in geschiedenis:
            delen.append(f"=== {b['spreker']} ===")
            delen.append(b["tekst"].strip())
            delen.append("")
    if not geschiedenis:
        delen.append(
            f"Jij bent {spreker}. Onderzoek de code/vraag en geef je eerste bevindingen KORT EN IN MENSENTAAL "
            "(max 350 woorden, beslissing eerst, per punt wat het voor Mehdi betekent + 1 regel techniek voor Claude)."
        )
    elif not is_slot:
        delen.append(
            f"Jij bent {spreker}. Reageer kort en in gewone mensentaal (max 350 woorden) op de vorige bijdrage: "
            "zeg waar je het mee eens bent, corrigeer wat niet klopt en voeg toe wat gemist werd."
        )
    else:
        delen.append(
            f"Jij bent {spreker}. Maak nu de GEZAMENLIJKE EINDCONCLUSIE (max 1 A4 / 400 woorden):\n"
            "Deel 1 — Voor Mehdi (in gewone mensentaal, zonder code):\n"
            "- Beslissing in 1 zin.\n"
            "- Kort per punt wat er nog mis kon gaan en hoe we het oplossen.\n"
            "- Eventuele keuzes die alleen Mehdi moet maken.\n\n"
            "Deel 2 — Voor Claude en Shaniel (compact technisch lijstje):\n"
            "- Per punt: nummer, ernst, `bestand:regel` en de exacte aanpassing."
        )
    return "\n".join(delen)


def draai_overleg(werkmap: Path, rapport: Path, titel: str, opdracht_tekst: str,
                  rondes: int = 2, codex_model: str = "", codex_niveau: str = "",
                  gemini_model: str = "gemini-4-argon", gemini_niveau: str = "high",
                  claude_model: str = "", claude_niveau: str = "",
                  met_claude: bool = False, timeout: int = 1200) -> int:
    adres, token = debat._antigravity_omgeving()
    if not ((adres and token) or os.environ.get("ANTIGRAVITY_LS_ADDRESS", "").strip()
            or os.environ.get("GEMINI_AGENTAPI", "").strip()):
        print("overleg.py: Gemini-toegang ontbreekt; start dit in de Terminal van Antigravity: "
              "Terminal > New Terminal", file=sys.stderr)
        return 2

    codex_model = codex_model or _codex_config("model") or "gpt-6-sol"
    codex_niveau = codex_niveau or _codex_config("model_reasoning_effort") or "high"
    codex_label = f"{codex_model} · {codex_niveau}" if codex_niveau else codex_model

    gem_m, gem_n, gem_enum, gemini_label, _ = debat.gemini_model_info(gemini_model, gemini_niveau)

    std_claude_m, std_claude_n = debat._claude_standaard()
    claude_model = claude_model or std_claude_m
    claude_niveau = claude_niveau or std_claude_n
    claude_label = f"{claude_model} · {claude_niveau}" if claude_niveau else claude_model

    rapport.parent.mkdir(parents=True, exist_ok=True)
    ronde_bestand = rapport.parent / (rapport.name + ".ronde")
    for p in (rapport, ronde_bestand):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass

    run_naam = ronde.nieuw(
        titel=titel,
        opdracht=opdracht_tekst,
        naambestand=str(ronde_bestand),
        project=str(werkmap),
        rapport=str(rapport),
        codex_model=codex_model,
        codex_niveau=codex_niveau,
        gemini_model=gem_m,
        gemini_niveau=gem_n,
        gemini_model_enum=gem_enum,
        claude_model=claude_label,
        claude_niveau=claude_niveau,
        niveau=codex_niveau,
        sandbox="read-only",
    )
    run_dir = ronde.run_pad(run_naam)
    geschiedenis = []

    # Standaard volgorde voor diepgaand overleg:
    # Ronde 1: Codex analyseert -> Gemini analyseert + reageert op Codex (en optioneel Claude bij --met-claude)
    # Ronde 2 (indien rondes >= 2): kruisreactie en gezamenlijke eindconclusie
    if met_claude:
        beurten_plan = ["codex", "gemini", "claude"]
        if rondes >= 2:
            for r in range(2, rondes + 1):
                beurten_plan.append("codex" if r % 2 == 0 else "gemini")
    else:
        beurten_plan = ["codex", "gemini"]
        if rondes >= 2:
            for r in range(2, rondes + 1):
                beurten_plan.append("codex" if len(beurten_plan) % 2 == 0 else "gemini")

    naam_kaart = {"codex": "Codex", "gemini": "Gemini", "claude": "Claude"}
    for idx, kant in enumerate(beurten_plan):
        is_slot = (idx == len(beurten_plan) - 1)
        prompt = bouw_overleg_prompt(
            opdracht_tekst, geschiedenis,
            naam_kaart[kant],
            is_slot=is_slot,
        )
        begin = time.monotonic()
        model_label = codex_label if kant == "codex" else (gemini_label if kant == "gemini" else claude_label)
        try:
            if kant == "codex":
                volledig = f"{SYSTEEM_OVERLEG}\n\n---\n\n{prompt}"
                tekst = roep_codex_in_map(werkmap, volledig, codex_model, codex_niveau, timeout)
            elif kant == "gemini":
                tekst = debat.roep_gemini(
                    SYSTEEM_OVERLEG, prompt, gemini_model, timeout,
                    werkmap=werkmap, niveau=gemini_niveau,
                )
            else:
                tekst = debat.roep_claude(
                    SYSTEEM_OVERLEG, prompt, claude_model, timeout,
                    niveau=claude_niveau, werkmap=werkmap,
                )
        except Exception as e:
            duur = round(time.monotonic() - begin, 1)
            ronde.voeg_toe(run_dir, kant, "fout", f"{kant} stopte met een fout: {e}", model=model_label, duur=duur)
            print(f"overleg.py: {kant} faalde ({e})", file=sys.stderr)
            return 1

        duur = round(time.monotonic() - begin, 1)
        if is_slot and kant == "codex":
            soort = "controle"
        elif is_slot and kant == "gemini":
            soort = "advies"
        else:
            soort = "overleg"
        beurt = ronde.voeg_toe(run_dir, kant, soort, tekst, model=model_label, duur=duur)
        geschiedenis.append(beurt)

    # Schrijf een compleet verslag naar rapport zodat Claude en Mehdi zowel de modellen/denkstanden,
    # de dialoog als de gezamenlijke eindconclusie zien.
    verslag_delen = [
        f"# Driehoeksoverleg (Codex, Gemini & Claude): {titel}",
        f"Ronde in dashboard: `{run_naam}` (http://127.0.0.1:8099)",
        "Modellen en denkstand:",
        f"- Claude: `{claude_model}` (denkstand: `{claude_niveau}`)",
        f"- Codex: `{codex_model}` (denkstand: `{codex_niveau}`)",
        f"- Gemini (Antigravity): `{gemini_label}` (`{gem_m}`, denkstand: `{gem_n}`)",
        "",
    ]
    for b in geschiedenis[:-1]:
        verslag_delen += [
            f"## {b['spreker']} ({b['model']}, {b['duur_s']}s)",
            "",
            b["tekst"].strip(),
            "",
        ]
    if geschiedenis:
        slot = geschiedenis[-1]
        verslag_delen += [
            f"## Gezamenlijke Eindconclusie — {slot['spreker']} ({slot['model']}, {slot['duur_s']}s)",
            "",
            slot["tekst"].strip(),
            "",
        ]
    volledig_rapport = "\n".join(verslag_delen)
    rapport.write_text(volledig_rapport, encoding="utf-8")
    print(volledig_rapport)
    print(f"overleg.sh: ronde {run_naam} staat in het dashboard (http://127.0.0.1:8099)", file=sys.stderr)
    return 0


def positieve_seconden(waarde: str) -> int:
    try:
        seconden = int(waarde)
    except ValueError as e:
        raise argparse.ArgumentTypeError("timeout moet een geheel getal groter dan 0 zijn") from e
    if seconden <= 0:
        raise argparse.ArgumentTypeError("timeout moet een geheel getal groter dan 0 zijn")
    return seconden


def geldige_gemini_model(waarde: str) -> str:
    try:
        debat.gemini_model_info(waarde, "high")
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e
    return waarde


def geldige_gemini_niveau(waarde: str) -> str:
    try:
        debat.gemini_model_info("gemini-4-argon", waarde)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e
    return waarde


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Driehoeksoverleg tussen Claude, Codex en Gemini")
    p.add_argument("-C", dest="map", required=True, help="Werkmap om te onderzoeken (alleen lezen)")
    p.add_argument("-o", dest="rapport", required=True, help="Uitvoerbestand voor het gezamenlijke rapport")
    p.add_argument("-t", dest="titel", default="", help="Titel in het dashboard")
    p.add_argument("-b", dest="beurten", type=int, default=2, help="Diepte van het overleg (1 = Codex+Gemini, 2 = + kruisreactie/synthese)")
    p.add_argument("-m", dest="codex_model", default="", help="Codex-model (bijv. gpt-6-sol, gpt-6-astra)")
    p.add_argument("-e", dest="codex_niveau", default="", help="Codex redeneerniveau (low, medium, high, xhigh, ultra)")
    p.add_argument("-g", dest="gemini_model", default="gemini-4-argon", type=geldige_gemini_model,
                   help="Gemini-model (gemini-4-argon, gemini-3.8-flash, pro, flash, flash_lite)")
    p.add_argument("-G", "--gemini-niveau", dest="gemini_niveau", default="high", type=geldige_gemini_niveau,
                   help="Gemini denkniveau (high, medium, low)")
    p.add_argument("-c", "--claude-model", dest="claude_model", default="",
                   help="Claude-model (bijv. claude-opus-5-5, opus, sonnet)")
    p.add_argument("-E", "--claude-niveau", dest="claude_niveau", default="",
                   help="Claude denkniveau (max, xhigh, high, medium, low)")
    p.add_argument("--met-claude", action="store_true",
                   help="Laat Claude ook zelfstandig een overlegbeurt draaien via de CLI")
    p.add_argument("-T", "--timeout", type=positieve_seconden, default=1200,
                   metavar="SECONDEN", help="Timeout per beurt (standaard 1200 seconden)")
    p.add_argument("--runs", default="", help="Andere runs-map (voor zelftest/tests)")
    args = p.parse_args(argv)

    if args.runs:
        debat.RUNS = Path(args.runs)
    werkmap = Path(args.map).resolve()
    if not werkmap.is_dir():
        print(f"overleg.py: map bestaat niet: {werkmap}", file=sys.stderr)
        return 2
    opdracht_tekst = sys.stdin.read().strip()
    if not opdracht_tekst:
        print("overleg.py: opdracht via stdin is leeg", file=sys.stderr)
        return 2
    rapport = Path(args.rapport)
    titel = args.titel or f"Overleg Codex+Gemini: {werkmap.name} - {rapport.stem}"
    return draai_overleg(
        werkmap=werkmap,
        rapport=rapport,
        titel=titel,
        opdracht_tekst=opdracht_tekst,
        rondes=max(1, min(6, args.beurten)),
        codex_model=args.codex_model,
        codex_niveau=args.codex_niveau,
        gemini_model=args.gemini_model,
        gemini_niveau=args.gemini_niveau,
        claude_model=args.claude_model,
        claude_niveau=args.claude_niveau,
        met_claude=args.met_claude,
        timeout=args.timeout,
    )


if __name__ == "__main__":
    sys.exit(main())
