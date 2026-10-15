"""Start Codex voor codex.sh in een eigen procesgroep, zodat de val van codex.sh de hele groep kan stoppen.

    python starter.py <groepsbestand> <codex> <argumenten...>

1. setsid: een eigen sessie en groep; het pid van dit proces is vanaf nu het groepsnummer.
2. Het groepsnummer gaat naar <groepsbestand>. $! in codex.sh is daarvoor niet genoeg: start python via een
   shellwrapper (pyenv, asdf), dan is $! de wrapper.
3. Staat <groepsbestand>.stop er, dan was codex.sh al onderbroken: niet meer starten. Zo kan een starter die
   gepauzeerd was terwijl de val opgaf, Codex achteraf nooit nog starten.
4. Anders exec van Codex in dit proces, dus in deze groep.

Alleen standaardbibliotheek.
"""

import os
import sys
import time


def main() -> int:
    groep, opdracht = sys.argv[1], sys.argv[2:]
    os.setsid()
    pauze = float(os.environ.get("CODEX_SH_TEST_STARTER_PAUZE", "0") or 0)  # alleen voor tests
    if pauze:
        time.sleep(pauze)
    fd = os.open(groep, os.O_WRONLY | os.O_TRUNC)
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    if os.path.exists(groep + ".stop"):
        return 143
    os.execvp(opdracht[0], opdracht)
    return 127  # niet bereikbaar: execvp keert alleen terug met een fout


if __name__ == "__main__":
    sys.exit(main())
