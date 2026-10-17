**Klaar voor Claude-controle.** Alleen deze worktree is gewijzigd; ik heb niet gecommit of gepusht.

1. [debat.py:173](/Users/mehdichegini/dev/_overleg-v11/debat.py:173): herkomst en onbewezen modelkoppeling genoteerd. De enumcodes zijn behouden.
2. [debat.py:341](/Users/mehdichegini/dev/_overleg-v11/debat.py:341), [overleg.py:219](/Users/mehdichegini/dev/_overleg-v11/overleg.py:219): serverfouten geven geen ruwe body, URL of sleutel meer door.
3. [debat.py:248](/Users/mehdichegini/dev/_overleg-v11/debat.py:248): Claude- en Antigravity-gegevens gaan alleen naar het bedoelde kindproces; Codex krijgt geen van beide.
4. [debat.py:185](/Users/mehdichegini/dev/_overleg-v11/debat.py:185), [overleg.py:138](/Users/mehdichegini/dev/_overleg-v11/overleg.py:138): onuitvoerbare model- en niveaukeuzes stoppen vóór de eerste beurt.
5. [debat.py:366](/Users/mehdichegini/dev/_overleg-v11/debat.py:366): mislukte sessieopruiming verschijnt in stderr en als foutbeurt.
6. [debat.py:408](/Users/mehdichegini/dev/_overleg-v11/debat.py:408): één deadline omvat Gemini starten en wachten.
7. [overleg.sh:43](/Users/mehdichegini/dev/_overleg-v11/overleg.sh:43): geërfde `CLAUDE_MODEL` blijft staan; `agentapi` is alleen vereist bij terugval.
8. [test_overleg.py:476](/Users/mehdichegini/dev/_overleg-v11/test_overleg.py:476): overtollige eindregel verwijderd.

Gedaan: herstel en stubtests toegevoegd.  
Nagekeken: **105 tests geslaagd, 2 overgeslagen**; `git diff --check` en `bash -n overleg.sh` geslaagd.  
Open: de koppeling van enumcode naar model en denkniveau moet nog tegen de echte server worden bewezen; Claude controleert en verzorgt daarna commit en push.