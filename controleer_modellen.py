"""Stelt vast welke modellen op DEZE machine met DEZE logins echt werken.

Welke modelnamen geldig zijn verschilt per account (ChatGPT-plan) en per CLI-versie
(een oude Claude Code weigert bijvoorbeeld `fable`). Daarom probeert dit script elke
kandidaat met een minimale vraag en schrijft alleen de werkende naar modellen.json.
De webinterface vult haar keuzelijsten uit dat bestand.

Gebruik:
    python controleer_modellen.py
    python controleer_modellen.py --codex gpt-7-iets --claude claude-iets   # extra kandidaten

Elke proef is een echte aanroep en telt dus mee in je gebruikslimiet, maar het gaat om
een paar woorden per model.
"""

import argparse
import json
import re
from datetime import datetime

import debat

CLAUDE_KANDIDATEN = ["sonnet", "opus", "haiku", "fable"]
CODEX_KANDIDATEN = ["gpt-6-astra", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"]
VRAAG = "Antwoord met alleen het woord: ok"


def probeer_claude(model: str) -> tuple:
    cmd = [debat.vind("claude"), "-p", "--safe-mode", "--tools", "",
           "--no-session-persistence", "--output-format", "text", "--model", model]
    try:
        code, uit, fout = debat._draai(cmd, VRAAG, 180, None)
    except Exception as e:
        return False, str(e)[:200]
    if code != 0:
        return False, (fout or uit).strip()[:200]
    return True, uit.strip()[:40]


def probeer_codex(model: str) -> tuple:
    cmd = [debat.vind("codex"), "exec", "--sandbox", "read-only", "--skip-git-repo-check",
           "--ephemeral", "--ignore-user-config", "--color", "never"]
    if model:
        cmd += ["--model", model]
    cmd += ["-"]
    try:
        code, uit, fout = debat._draai(cmd, VRAAG, 180, None)
    except Exception as e:
        return False, str(e)[:200]
    geheel = uit + "\n" + fout
    if code != 0 or "ERROR:" in geheel:
        melding = next((r for r in geheel.splitlines() if "ERROR" in r), geheel.strip())
        return False, melding[:200]
    # Codex zet de werkelijke modelnaam in zijn kopregels; die tonen we als label.
    gevonden = re.search(r"^model:\s*(\S+)", geheel, re.M)
    return True, gevonden.group(1) if gevonden else (model or "standaard")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--claude", nargs="*", default=[], help="extra Claude-modellen om te proberen")
    p.add_argument("--codex", nargs="*", default=[], help="extra Codex-modellen om te proberen")
    args = p.parse_args()

    resultaat = {"gecontroleerd_op": datetime.now().isoformat(timespec="seconds"),
                 "claude": [], "codex": [], "geweigerd": {"claude": [], "codex": []}}

    for model in dict.fromkeys(CLAUDE_KANDIDATEN + args.claude):
        ok, info = probeer_claude(model)
        print(f"claude {model:<14} {'werkt' if ok else 'GEWEIGERD'}  {'' if ok else info}")
        if ok:
            resultaat["claude"].append({"waarde": model, "label": model})
        else:
            resultaat["geweigerd"]["claude"].append({"model": model, "reden": info})

    # Eerst het standaardmodel, zodat we weten hoe het echt heet.
    ok, naam = probeer_codex("")
    print(f"codex  {'(standaard)':<14} {'werkt, heet ' + naam if ok else 'GEWEIGERD  ' + naam}")
    if ok:
        resultaat["codex"].append({"waarde": "", "label": f"{naam} (standaard)"})
    else:
        resultaat["geweigerd"]["codex"].append({"model": "(standaard)", "reden": naam})
    standaard = naam if ok else None

    for model in dict.fromkeys(CODEX_KANDIDATEN + args.codex):
        if model == standaard:
            continue
        ok, info = probeer_codex(model)
        print(f"codex  {model:<14} {'werkt' if ok else 'GEWEIGERD'}  {'' if ok else info}")
        if ok:
            resultaat["codex"].append({"waarde": model, "label": model})
        else:
            resultaat["geweigerd"]["codex"].append({"model": model, "reden": info})

    if not resultaat["claude"] or not resultaat["codex"]:
        print("\nMinstens een kant heeft geen enkel werkend model. modellen.json NIET "
              "overschreven. Controleer eerst de logins (zie CLAUDE.md, stap 3).")
        return 1

    (debat.BASIS / "modellen.json").write_text(
        json.dumps(resultaat, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nmodellen.json geschreven: {len(resultaat['claude'])} Claude-modellen, "
          f"{len(resultaat['codex'])} Codex-modellen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
