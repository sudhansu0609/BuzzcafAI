"""No console flashes on Windows.

The Studio runs under pythonw (no console), so every console program it starts
(ffmpeg, nvidia-smi, lms, taskkill, powershell, ...) gets a console window of
its own that flashes open and shut. `apply()` makes `subprocess.Popen` add
CREATE_NO_WINDOW to every child that does not ask for its own console or a
detached process; asyncio's subprocess support goes through Popen, so it is
covered too. GUI programs (BuzzEdit, Explorer) are unaffected by the flag.
"""

import os
import subprocess

CREATE_NO_WINDOW = 0x08000000
_CREATE_NEW_CONSOLE = 0x00000010
_DETACHED_PROCESS = 0x00000008

_applied = False


def apply() -> None:
    global _applied
    if _applied or os.name != "nt":
        return
    _applied = True
    original = subprocess.Popen.__init__

    def __init__(self, *args, **kwargs):  # noqa: N807
        flags = kwargs.get("creationflags", 0) or 0
        if not flags & (_CREATE_NEW_CONSOLE | _DETACHED_PROCESS):
            kwargs["creationflags"] = flags | CREATE_NO_WINDOW
        original(self, *args, **kwargs)

    subprocess.Popen.__init__ = __init__
