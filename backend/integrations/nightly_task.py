"""The nightly run's Windows side: Task Scheduler tasks that WAKE the PC
(from sleep or hibernate) at their own time (IST, the machine's zone) and
start `nightly_run.py`, plus the power setting that lets it.

There is one task per scheduler, each with its own time: "shorts" (the Shorts
Desk batch, `nightly_time`) and "longform" (the long-form batch,
`longform_time`). Each runs `nightly_run.py --only <scope>`.

- The task is per-user ("run only when the user is logged on"): hibernate
  keeps the session, so no password or admin rights are needed.
- Windows ignores WakeToRun unless "Allow wake timers" is on for the active
  power plan; `enable_wake_timers()` sets it (AC and battery) -- it was off
  on this machine.
- StartWhenAvailable: a run missed because the PC was fully shut down starts
  at the next boot instead of being skipped.
"""
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger("buzzcaf_ai.nightly_task")

TASK_NAME = r"BuzzcafStudio\NightlyRun"  # the shorts task (name kept for the task already registered)
TASK_NAMES = {"shorts": TASK_NAME, "longform": r"BuzzcafStudio\LongformRun"}
_LABELS = {"shorts": "runs the Shorts Desk batch (all channels)",
           "longform": "runs the long-form batch (one video per channel)"}
BACKEND_DIR = Path(__file__).resolve().parents[1]
RUNNER = BACKEND_DIR / "nightly_run.py"
# "Allow wake timers" in the Sleep subgroup of the power plan.
_SUB_SLEEP = "238c9fa8-0aad-41ed-83f4-97be242c8f20"
_RTCWAKE = "bd3b718a-0680-4d9d-8ab2-e1d2b4ac806d"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run(args, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, creationflags=_NO_WINDOW)


def _python() -> str:
    """pythonw beside the interpreter running the Studio: no console window at 3 AM."""
    exe = Path(sys.executable)
    windowless = exe.with_name("pythonw.exe")
    return str(windowless if windowless.exists() else exe)


def wake_timers_enabled() -> bool:
    out = _run(["powercfg", "/q", "SCHEME_CURRENT", _SUB_SLEEP, _RTCWAKE]).stdout
    return "Current AC Power Setting Index: 0x00000001" in out


def enable_wake_timers() -> bool:
    ok = True
    for flag in ("/setacvalueindex", "/setdcvalueindex"):
        ok &= _run(["powercfg", flag, "SCHEME_CURRENT", _SUB_SLEEP, _RTCWAKE, "1"]).returncode == 0
    ok &= _run(["powercfg", "/setactive", "SCHEME_CURRENT"]).returncode == 0
    return ok and wake_timers_enabled()


def _first_day(hhmm: str) -> str:
    """Today, unless the time is under 3 h away (or past): then tomorrow --
    registering at 02:10 for 03:00 must not wake-and-hibernate the PC in the
    middle of whatever the creator is doing right now."""
    from datetime import datetime, timedelta
    now = datetime.now()
    hh, mm = (int(x) for x in hhmm.split(":")[:2])
    first = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if first - now < timedelta(hours=3):
        first += timedelta(days=1)
    return first.strftime("%Y-%m-%d")


def time_limit_hours() -> int:
    """How long Windows lets a run go before it kills it (config
    `nightly_time_limit_hours`, 12 by default). It was 4: on 2026-10-26 the
    long-form run was killed at 07:00 with 1 of 8 videos done (0x41306)."""
    try:
        from integrations.llm import load_config
        return max(1, min(23, int(load_config().get("nightly_time_limit_hours") or 12)))
    except (TypeError, ValueError):
        return 12


def _task_xml(hhmm: str, scope: str = "shorts") -> str:
    user = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}".strip("\\")
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Buzzcaf Studio {scope} run: wakes the PC, {_LABELS[scope]}, offloads every model, and hibernates again if nothing else is using the GPU. Managed from Buzzcaf Studio -&gt; Scheduler Desk.</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{_first_day(hhmm)}T{hhmm}:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{user}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>true</WakeToRun>
    <ExecutionTimeLimit>PT{time_limit_hours()}H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{_python()}</Command>
      <Arguments>"{RUNNER}" --only {scope}</Arguments>
      <WorkingDirectory>{BACKEND_DIR}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _name(scope: str) -> str:
    if scope not in TASK_NAMES:
        raise ValueError(f"unknown scheduler scope: {scope}")
    return TASK_NAMES[scope]


def register(hhmm: str, scope: str = "shorts") -> Dict[str, Any]:
    """(Re)create the scope's task for HH:MM daily and make sure wake timers are on."""
    wake = enable_wake_timers()
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-16") as f:
        f.write(_task_xml(hhmm, scope))
        path = f.name
    try:
        proc = _run(["schtasks", "/create", "/tn", _name(scope), "/xml", path, "/f"])
    finally:
        os.unlink(path)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip() or "schtasks failed")
    logger.info("%s task registered for %s (wake timers %s)", scope, hhmm, "on" if wake else "NOT on")
    return status(scope)


def unregister(scope: str = "shorts") -> Dict[str, Any]:
    _run(["schtasks", "/delete", "/tn", _name(scope), "/f"])
    return status(scope)


def run_now(scope: str = "shorts") -> bool:
    return _run(["schtasks", "/run", "/tn", _name(scope)]).returncode == 0


def status(scope: str = "shorts") -> Dict[str, Any]:
    proc = _run(["schtasks", "/query", "/tn", _name(scope), "/fo", "LIST", "/v"])
    info: Dict[str, Any] = {"registered": proc.returncode == 0, "wake_timers": wake_timers_enabled()}
    if proc.returncode == 0:
        for line in proc.stdout.splitlines():
            key, _, value = line.partition(":")
            key = key.strip()
            if key in ("Next Run Time", "Last Run Time", "Last Result", "Status"):
                info[key.lower().replace(" ", "_")] = value.strip()
    return info
