"""
tests/test_kill_switch.py

Pure unit tests for core.kill_switch — no Neo4j / Ollama required.
"""
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from core.kill_switch import KillSwitch, KillSwitchActiveError


@pytest.fixture(autouse=True)
def _clean_state():
    # Make sure each test starts from a known "not active" state.
    KillSwitch.disengage()
    os.environ["KILL_SWITCH_ENABLED"] = "false"
    yield
    KillSwitch.disengage()
    os.environ["KILL_SWITCH_ENABLED"] = "false"


def test_inactive_by_default():
    assert KillSwitch.is_active() is False
    KillSwitch.enforce()  # should not raise


def test_env_flag_activates_switch(monkeypatch):
    # is_active() reloads .env with override=True by design (so a live edit
    # to .env takes effect without a restart) — that would otherwise clobber
    # monkeypatch.setenv with whatever's on disk, so we stub the reload out
    # for this test and set the env var directly instead.
    monkeypatch.setattr("core.kill_switch.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("KILL_SWITCH_ENABLED", "true")
    assert KillSwitch.is_active() is True
    with pytest.raises(KillSwitchActiveError):
        KillSwitch.enforce()


def test_runtime_flag_file_activates_switch():
    KillSwitch.engage(reason="unit test")
    assert KillSwitch.is_active() is True
    with pytest.raises(KillSwitchActiveError):
        KillSwitch.enforce()

    KillSwitch.disengage()
    assert KillSwitch.is_active() is False
    KillSwitch.enforce()  # should not raise anymore


def test_status_reports_both_flags():
    KillSwitch.engage(reason="unit test")
    status = KillSwitch.status()
    assert status["active"] is True
    assert status["flag_file_present"] is True
