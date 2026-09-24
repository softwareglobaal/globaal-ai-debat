"""Snelle rooktest per kant, zodat we de CLI-vlaggen los kunnen verifieren."""
import sys
import debat

kant = sys.argv[1] if len(sys.argv) > 1 else "claude"
systeem = debat.HUISREGELS.format(max_woorden=60)
prompt = "ONDERWERP\nIs koffie beter dan thee?\n\nJOUW POSITIE\nJij verdedigt koffie.\n\nOpen het debat. Maximaal 60 woorden."

if kant == "claude":
    print(debat.roep_claude(systeem, prompt, "sonnet", 180))
else:
    print(debat.roep_codex(systeem, prompt, "", 180))
