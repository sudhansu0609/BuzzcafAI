"""The Studio obeys the port law (GUARDIAN_PLAN.md section 11).

Nothing is hardcoded past the preferred default, the preferred port is a wish,
a busy port is stepped over rather than evicted, and where we landed is written
into the shared ledger and taken out again on the way down.
"""
import hashlib
import json
import os
import socket
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import desktop_app
from app.main import APP_ID, app, bound_port, set_bound_port
from integrations import buzzcaf_ports

client = TestClient(app)

BACKEND = Path(__file__).resolve().parent.parent
CANONICAL = BACKEND.parent.parent / "dexter" / "backend" / "buzzcaf_ports.py"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "ports.json"
    monkeypatch.setenv("BUZZCAF_PORTS_FILE", str(path))
    return path


@pytest.fixture
def occupied():
    """A dummy listener holding a port, the way another app would."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    try:
        yield sock.getsockname()[1]
    finally:
        sock.close()


def test_health_says_who_and_where_we_are():
    body = client.get("/health").json()
    assert body["app"] == APP_ID == "buzzcaf"
    assert body["status"] == "ok"
    assert body["port"] == bound_port()
    assert body["pid"] == os.getpid()


def test_health_reports_the_port_we_actually_bound():
    before = bound_port()
    try:
        set_bound_port(before + 7)
        assert client.get("/health").json()["port"] == before + 7
    finally:
        set_bound_port(before)


@pytest.mark.skipif(not CANONICAL.exists(), reason="Dexter checkout not beside this one")
def test_the_port_helper_is_a_byte_identical_copy():
    assert _digest(BACKEND / "integrations" / "buzzcaf_ports.py") == _digest(CANONICAL)


def test_pick_port_steps_forward_instead_of_evicting(occupied):
    holder_is_still_there = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        chosen = buzzcaf_ports.pick_port(occupied)
        assert chosen != occupied
        assert occupied < chosen <= occupied + buzzcaf_ports.SPAN
        # The other app kept its port: a second bind still fails.
        with pytest.raises(OSError):
            holder_is_still_there.bind(("127.0.0.1", occupied))
            holder_is_still_there.listen(1)
    finally:
        holder_is_still_there.close()


def test_resolve_port_steps_past_a_stranger(occupied, ledger, monkeypatch):
    monkeypatch.setattr(desktop_app, "_read_runtime", lambda: {})
    port, attached = desktop_app._resolve_port(occupied)
    assert attached is False
    assert port != occupied


def test_publish_then_withdraw_leaves_the_ledger_clean(ledger, monkeypatch):
    monkeypatch.setattr(desktop_app, "_write_runtime", lambda port: None)
    monkeypatch.setattr(desktop_app, "_read_runtime", lambda: {"pid": os.getpid()})
    monkeypatch.setattr(os, "remove", lambda path: None)

    desktop_app._publish(9999, extra={"vite": 5173})
    entry = json.loads(ledger.read_text(encoding="utf-8"))["buzzcaf"]
    assert entry["port"] == 9999
    assert entry["pid"] == os.getpid()
    assert entry["health"] == "http://127.0.0.1:9999/health"
    assert entry["extra"] == {"vite": 5173}

    desktop_app._clear_runtime()
    assert "buzzcaf" not in json.loads(ledger.read_text(encoding="utf-8"))


def test_publish_does_not_disturb_another_apps_entry(ledger, monkeypatch):
    monkeypatch.setattr(desktop_app, "_write_runtime", lambda port: None)
    buzzcaf_ports.publish("dexter", 8098, "http://127.0.0.1:8098/health")
    desktop_app._publish(8099)
    data = json.loads(ledger.read_text(encoding="utf-8"))
    assert set(data) == {"dexter", "buzzcaf"}


def test_no_port_is_hardcoded_beyond_the_preferred_default():
    """The only port literals in the launcher are the two `<APP>_PORT` defaults.

    Tokenised rather than grepped, so a number inside a docstring or a comment
    (there are several, explaining *why* 8099) is not mistaken for a decision.
    """
    import io
    import tokenize

    source = (BACKEND / "desktop_app.py").read_text(encoding="utf-8")
    lines = source.splitlines()
    offenders = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.NUMBER:
            continue
        try:
            value = int(token.string)
        except ValueError:
            continue
        if not (1024 <= value <= 65535):
            continue
        line = lines[token.start[0] - 1]
        if "port" in line.lower() and "getenv" not in line:
            offenders.append((token.start[0], line.strip()))
    assert not offenders, f"hardcoded ports left in desktop_app.py: {offenders}"


def test_the_preferred_ports_come_from_the_environment(monkeypatch):
    import importlib
    import logging

    monkeypatch.setenv("BUZZCAF_PORT", "8123")
    monkeypatch.setenv("BUZZCAF_DEV_PORT", "4321")
    handlers = list(logging.getLogger().handlers)
    try:
        reloaded = importlib.reload(desktop_app)
        assert reloaded.PORT == 8123
        assert reloaded.DEV_PORT == 4321
    finally:
        monkeypatch.undo()
        importlib.reload(desktop_app)
        logging.getLogger().handlers[:] = handlers


# ─────────── leaving the ledger on the way down (P4 integration defect) ───────────


def test_the_shutdown_hook_withdraws_the_entry(monkeypatch, tmp_path):
    """A graceful stop must take the entry out *inside* the app's shutdown.

    On Windows a console control event (Ctrl+Break, closing the console window,
    the machine shutting down) ends the process from the CRT's default handler
    the moment uvicorn's own handler returns. `atexit` and the `finally` around
    `uvicorn.run` never run. That is what the P4 integration run saw: the Studio
    stopped cleanly and left `buzzcaf -> 8099` in the ledger naming a dead pid,
    which every consumer then had to probe and discard. FastAPI's `shutdown`
    event fires *before* the process is torn down, so it is the last point that
    is still reliably ours.
    """
    from app import main as studio_main

    ledger = tmp_path / "ports.json"
    monkeypatch.setenv("BUZZCAF_PORTS_FILE", str(ledger))
    buzzcaf_ports._forget()
    buzzcaf_ports.publish(APP_ID, 8099, "http://127.0.0.1:8099/health")
    assert buzzcaf_ports.entry(APP_ID)

    # As `serve_headless` leaves it: this process owns the entry.
    monkeypatch.setattr(studio_main, "_owns_ledger_entry", True)
    with TestClient(app):
        pass  # entering runs startup, leaving runs shutdown

    assert buzzcaf_ports.entry(APP_ID) is None, (
        "the Studio's shutdown left its ledger entry behind"
    )


def test_a_process_that_does_not_own_the_entry_leaves_it_alone(monkeypatch, tmp_path):
    """Under the desktop launcher the entry belongs to the launcher.

    It is the only party that knows which sub-services went with this backend,
    so a backend that withdrew on its own behalf would delete a record it did
    not write and make the launcher's app unfindable while it is still running.
    """
    from app import main as studio_main

    ledger = tmp_path / "ports.json"
    monkeypatch.setenv("BUZZCAF_PORTS_FILE", str(ledger))
    buzzcaf_ports._forget()
    buzzcaf_ports.publish(APP_ID, 8099, "http://127.0.0.1:8099/health")

    monkeypatch.setattr(studio_main, "_owns_ledger_entry", False)
    with TestClient(app):
        pass

    assert buzzcaf_ports.entry(APP_ID) is not None, (
        "the backend withdrew an entry it does not own"
    )
